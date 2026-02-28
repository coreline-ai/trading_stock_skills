from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class MarketBreadthAnalyzer(SkillAnalyzer):
    slug = "market-breadth-analyzer"
    _CACHE_REVISION = 2

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        min_breadth = _to_float(params.get("min_breadth"), 0.55)
        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "min_breadth": min_breadth,
                "cache_revision": self._CACHE_REVISION,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        state, source = context.market_provider.load_market_state_with_source()
        source_state = "live" if source == "fmp_live" else "stale"

        participation = max(0.0, min(1.0, state.breadth_up_ratio))
        volatility = max(0.0, min(1.0, 1.0 - ((state.vix_level - 12.0) / 18.0)))
        macro = max(0.0, min(1.0, 1.0 - state.recession_risk))
        trend = max(0.0, min(1.0, (state.spy_return_1d + state.qqq_return_1d + 2.0) / 4.0))
        small_cap = max(0.0, min(1.0, (state.iwm_return_1d + 2.0) / 4.0))
        leaders = sorted(
            state.symbols,
            key=lambda x: (x.ai_factor * 100 + x.momentum_20d + x.daily_return_pct * 0.5),
            reverse=True,
        )[:8]
        leadership = _leadership_score(leaders)

        factor_scores = {
            "participation": round(participation * 100, 2),
            "trend": round(trend * 100, 2),
            "volatility": round(volatility * 100, 2),
            "macro": round(macro * 100, 2),
            "small_cap_confirmation": round(small_cap * 100, 2),
            "leadership": round(leadership * 100, 2),
        }
        breadth_score = round(sum(factor_scores.values()) / len(factor_scores), 2)

        payload = {
            "breadth_score_0_100": breadth_score,
            "factor_scores": factor_scores,
            "index_snapshot": {
                "spy_return_1d": state.spy_return_1d,
                "qqq_return_1d": state.qqq_return_1d,
                "iwm_return_1d": state.iwm_return_1d,
                "vix_level": state.vix_level,
                "breadth_up_ratio": state.breadth_up_ratio,
                "recession_risk": state.recession_risk,
            },
            "leaders": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "momentum_20d": round(item.momentum_20d, 2),
                    "daily_return_pct": round(item.daily_return_pct, 2),
                    "ai_factor": round(item.ai_factor, 3),
                    "score": round(item.ai_factor * 45.0 + item.momentum_20d * 2.8 + item.daily_return_pct * 1.2, 2),
                }
                for item in leaders
            ],
            "above_threshold": state.breadth_up_ratio >= min_breadth,
            "regime_hint": _regime_hint(breadth_score),
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=12)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state)

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], source_state: str) -> SkillRunResultV2:
        score = _to_float(payload.get("breadth_score_0_100"), 50.0)
        confidence = 0.7 if source_state == "live" else 0.62
        threshold_msg = "충족" if payload.get("above_threshold") else "미충족"

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"6팩터 breadth score {score:.1f} (임계치 {threshold_msg})",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def _leadership_score(leaders: list[Any]) -> float:
    if not leaders:
        return 0.5
    avg_momentum = sum(max(-10.0, min(15.0, item.momentum_20d)) for item in leaders) / max(1, len(leaders))
    return max(0.0, min(1.0, (avg_momentum + 10.0) / 25.0))


def _regime_hint(score: float) -> str:
    if score >= 65:
        return "Risk-On"
    if score >= 50:
        return "Balanced"
    return "Risk-Off"


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"
