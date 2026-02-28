from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class EarningsTradeAnalyzer(SkillAnalyzer):
    slug = "earnings-trade-analyzer"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        days = _to_int(params.get("days"), 7)
        min_market_cap = _to_float(params.get("min_market_cap"), 5_000_000_000)

        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "days": days,
                "min_market_cap": min_market_cap,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        candidates: list[dict[str, Any]] = []
        mode = "proxy_from_market_state"
        source_state = "stale"

        if context.fmp_calendar is not None:
            try:
                raw = context.fmp_calendar.get_earnings_calendar(
                    start=context.as_of_date,
                    end=context.as_of_date + timedelta(days=max(1, days)),
                )
                candidates = _from_fmp_events(raw, min_market_cap=min_market_cap)
                if candidates:
                    mode = "fmp_calendar"
                    source_state = "live"
            except Exception:
                context.warnings.append(f"{self.slug}: FMP earnings fetch failed -> proxy fallback")

        if not candidates:
            state = context.market_provider.load_market_state()
            candidates = _from_market_state(state.symbols, as_of=context.as_of_date, days=days)

        payload = {
            "mode": mode,
            "candidates": candidates[:30],
            "window_days": max(1, days),
            "min_market_cap": min_market_cap,
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=12)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state)

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], source_state: str) -> SkillRunResultV2:
        candidates = payload.get("candidates", [])
        avg_setup = 0.0
        if candidates:
            avg_setup = sum(_to_float(item.get("setup_score"), 0.0) for item in candidates[:10]) / min(10, len(candidates))

        score = max(0.0, min(100.0, 40.0 + avg_setup * 0.7))
        confidence = 0.74 if source_state == "live" else 0.58

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"실적 트레이드 후보 {len(candidates)}건을 우선순위화했습니다.",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def _from_fmp_events(raw: list[dict[str, Any]], min_market_cap: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw[:500]:
        market_cap = _to_float(item.get("marketCap"), 0.0)
        if market_cap < min_market_cap:
            continue

        ticker = str(item.get("symbol") or "").upper()
        if not ticker:
            continue

        timing = _normalize_timing(item.get("time") or item.get("publishingTime"))
        date_text = str(item.get("date") or item.get("fiscalDateEnding") or "")[:10]

        # Simple setup proxy: size + timing preference + EPS estimate presence
        setup = 50.0
        setup += min(25.0, market_cap / 200_000_000_000)
        setup += 8.0 if timing in {"AMC", "BMO"} else 3.0
        setup += 6.0 if item.get("epsEstimated") is not None else 0.0

        rows.append(
            {
                "date": date_text,
                "ticker": ticker,
                "company": str(item.get("name") or item.get("companyName") or ticker),
                "timing": timing,
                "market_cap": market_cap,
                "setup_score": round(min(100.0, setup), 2),
                "setup_note": "실적 이벤트 전후 변동성/유동성 기반 후보",
                "source_url": "https://financialmodelingprep.com",
            }
        )

    rows.sort(key=lambda x: x["setup_score"], reverse=True)
    return rows


def _from_market_state(symbols: list[Any], as_of: Any, days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ranked = sorted(symbols, key=lambda x: (x.ai_factor * 100 + x.momentum_20d), reverse=True)

    for idx, item in enumerate(ranked[:20]):
        event_date = (as_of + timedelta(days=(idx % max(1, days)) + 1)).isoformat()
        setup = 45.0 + max(-10.0, min(20.0, item.momentum_20d * 1.8)) + item.ai_factor * 15
        rows.append(
            {
                "date": event_date,
                "ticker": item.symbol,
                "company": item.name,
                "timing": "AMC" if idx % 2 == 0 else "BMO",
                "market_cap": 0.0,
                "setup_score": round(max(0.0, min(100.0, setup)), 2),
                "setup_note": "FMP 미연결 상태에서 모멘텀/AI factor 기반 프록시 후보",
                "source_url": "",
            }
        )

    rows.sort(key=lambda x: x["setup_score"], reverse=True)
    return rows


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
