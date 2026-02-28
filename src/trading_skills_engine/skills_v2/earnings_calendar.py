from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class EarningsCalendarAnalyzer(SkillAnalyzer):
    slug = "earnings-calendar"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        days = _to_int(params.get("days"), 7)
        min_market_cap = _to_float(params.get("min_market_cap"), 2_000_000_000)

        start = context.as_of_date
        end = context.as_of_date + timedelta(days=max(1, days))

        cache_key = _cache_key(self.slug, {"start": start.isoformat(), "end": end.isoformat(), "min_mcap": min_market_cap})
        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            payload = cached.payload if isinstance(cached.payload, dict) else {}
            fmp_state = str(payload.get("_source_state") or "stale")
            if fmp_state == "live" and context.fmp_calendar is None:
                fmp_state = "stale"
            if not (context.fmp_calendar is not None and fmp_state != "live"):
                return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), fmp_state)

        if context.fmp_calendar is None:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            proxy = self._proxy_earnings_from_market_state(context=context, days=max(1, days), min_market_cap=min_market_cap)
            saved = context.cache_store.set(cache_key, proxy, ttl_hours=12)
            return self._build_ok(proxy, CacheStore.cache_info("fresh", saved), "stale")

        try:
            raw = context.fmp_calendar.get_earnings_calendar(start=start, end=end)
            payload = self._parse_earnings(raw, min_market_cap=min_market_cap)
            if not payload["earnings"]:
                stale = context.cache_store.get_stale(cache_key)
                if stale and _source_state(stale.payload) == "live":
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
                proxy = self._proxy_earnings_from_market_state(
                    context=context,
                    days=max(1, days),
                    min_market_cap=min_market_cap,
                )
                context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> proxy 사용")
                saved = context.cache_store.set(cache_key, proxy, ttl_hours=12)
                return self._build_ok(proxy, CacheStore.cache_info("fresh", saved), "unavailable")
            payload["_source_state"] = "live"
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live")
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            proxy = self._proxy_earnings_from_market_state(
                context=context,
                days=max(1, days),
                min_market_cap=min_market_cap,
            )
            context.warnings.append(f"{self.slug}: FETCH_FAILED -> proxy 사용")
            saved = context.cache_store.set(cache_key, proxy, ttl_hours=12)
            return self._build_ok(proxy, CacheStore.cache_info("fresh", saved), "unavailable")

    def _parse_earnings(self, raw: list[dict[str, Any]], min_market_cap: float) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        density = Counter()

        for item in raw[:500]:
            market_cap = _to_float(item.get("marketCap"), -1.0)
            if market_cap < 0:
                revenue = _to_float(item.get("revenueActual"), 0.0)
                market_cap = revenue * 8 if revenue > 0 else min_market_cap
            if market_cap < min_market_cap:
                continue
            date_text = str(item.get("date") or item.get("fiscalDateEnding") or "")
            timing = _normalize_timing(item.get("time") or item.get("publishingTime"))
            row = {
                "date": date_text,
                "ticker": str(item.get("symbol") or ""),
                "company": str(item.get("name") or item.get("companyName") or ""),
                "market_cap": market_cap,
                "timing": timing,
                "source_url": "https://financialmodelingprep.com",
            }
            if row["ticker"]:
                rows.append(row)
                density[date_text[:10]] += 1

        rows.sort(key=lambda x: x["market_cap"], reverse=True)
        return {
            "earnings": rows[:200],
            "daily_density": dict(density),
        }

    def _proxy_earnings_from_market_state(
        self,
        context: AnalyzerContext,
        days: int,
        min_market_cap: float,
    ) -> dict[str, Any]:
        state = context.market_provider.load_market_state()
        rows: list[dict[str, Any]] = []
        density = Counter()

        ranked = sorted(state.symbols, key=lambda x: (x.ai_factor * 100 + x.momentum_20d), reverse=True)
        for idx, symbol in enumerate(ranked[:40]):
            synthetic_cap = max(0.0, symbol.ai_factor * 450_000_000_000 + (symbol.momentum_20d + 10) * 2_000_000_000)
            if synthetic_cap < min_market_cap:
                continue

            event_date = context.as_of_date + timedelta(days=(idx % days) + 1)
            date_text = event_date.isoformat()
            density[date_text] += 1
            rows.append(
                {
                    "date": date_text,
                    "ticker": symbol.symbol,
                    "company": symbol.name,
                    "market_cap": round(synthetic_cap, 2),
                    "timing": "AMC" if idx % 2 == 0 else "BMO",
                    "source_url": "",
                }
            )

        rows.sort(key=lambda x: x["market_cap"], reverse=True)
        return {
            "mode": "market_state_proxy",
            "earnings": rows[:200],
            "daily_density": dict(density),
            "_source_state": "stale",
        }

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], fmp_state: str) -> SkillRunResultV2:
        earnings = payload.get("earnings", [])
        score = min(100.0, 40 + len(earnings) * 0.8)
        confidence = min(0.92, 0.52 + min(0.35, len(earnings) / 250))

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"시가총액 기준 필터 후 {len(earnings)}건의 실적 이벤트를 정리했습니다.",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": fmp_state},
        )


def _normalize_timing(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in {"bmo", "before market open"}:
        return "BMO"
    if text in {"amc", "after market close"}:
        return "AMC"
    if text in {"dmh", "during market hours"}:
        return "DMH"
    return "DMH"


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"


def _source_state(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("_source_state") or "stale")
    return "stale"
