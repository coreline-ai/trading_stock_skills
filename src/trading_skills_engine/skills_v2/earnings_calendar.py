from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
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
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "live")

        if context.fmp_calendar is None:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="FMP API 키가 없어 실적 캘린더를 조회할 수 없습니다.",
                reason_code="NO_API_KEY",
                source_statuses={"fmp": "unavailable"},
            )

        try:
            raw = context.fmp_calendar.get_earnings_calendar(start=start, end=end)
            payload = self._parse_earnings(raw, min_market_cap=min_market_cap)
            if not payload["earnings"]:
                stale = context.cache_store.get_stale(cache_key)
                if stale:
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="실적 캘린더 소스가 비어 있어 분석할 수 없습니다.",
                    reason_code="EMPTY_SOURCE",
                    source_statuses={"fmp": "unavailable"},
                )
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live")
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="실적 캘린더 조회에 실패했습니다.",
                reason_code="FETCH_FAILED",
                source_statuses={"fmp": "unavailable"},
            )

    def _parse_earnings(self, raw: list[dict[str, Any]], min_market_cap: float) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        density = Counter()

        for item in raw[:500]:
            market_cap = _to_float(item.get("marketCap"), 0.0)
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
