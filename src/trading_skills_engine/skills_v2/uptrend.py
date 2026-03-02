from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class UptrendAnalyzer(SkillAnalyzer):
    slug = "uptrend-analyzer"
    _CACHE_REVISION = 3

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        min_momentum = _to_float(params.get("min_momentum"), 2.0)
        market_scope = str(context.market_provider.get_market_scope() or "US").upper()
        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "min_momentum": min_momentum,
                "market_scope": market_scope,
                "cache_revision": self._CACHE_REVISION,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        try:
            state, source = context.market_provider.load_market_state_with_source()
        except Exception:
            scope = str(context.market_provider.get_market_scope() or "US").upper()
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko=f"{scope} 유니버스를 불러오지 못해 상승추세 분석을 수행할 수 없습니다.",
                reason_code="UNIVERSE_LOAD_FAILED",
                source_statuses={"fmp": "unavailable"},
            )
        source_state = "live" if source == "fmp_live" else "stale"

        tradable = list(state.symbols)
        uptrend_symbols = [item for item in tradable if item.momentum_20d >= min_momentum and item.daily_return_pct > -1.0]
        participation = len(uptrend_symbols) / max(1, len(tradable))

        leaders = sorted(
            uptrend_symbols,
            key=lambda x: (x.momentum_20d * 2 + x.ai_factor * 100 + x.daily_return_pct),
            reverse=True,
        )[:10]

        payload = {
            "uptrend_participation": round(participation, 4),
            "uptrend_count": len(uptrend_symbols),
            "universe_count": len(tradable),
            "leaders": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "momentum_20d": round(item.momentum_20d, 2),
                    "daily_return_pct": round(item.daily_return_pct, 2),
                    "ai_factor": round(item.ai_factor, 3),
                }
                for item in leaders
            ],
            "top_candidates": [
                {
                    "symbol": item.symbol,
                    "composite_score": round(item.ai_factor * 55.0 + item.momentum_20d * 2.4 + item.daily_return_pct * 1.1, 2),
                    "momentum_20d": round(item.momentum_20d, 2),
                    "daily_return_pct": round(item.daily_return_pct, 2),
                    "ai_factor": round(item.ai_factor, 3),
                }
                for item in leaders
            ],
            "thresholds": {"min_momentum": min_momentum},
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=12)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state)

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], source_state: str) -> SkillRunResultV2:
        participation = _to_float(payload.get("uptrend_participation"), 0.0)
        score = max(0.0, min(100.0, 35 + participation * 70))
        confidence = 0.72 if source_state == "live" else 0.64

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=(
                f"상승 추세 참여율 {participation * 100:.1f}% "
                f"({payload.get('uptrend_count', 0)}/{payload.get('universe_count', 0)})"
            ),
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"
