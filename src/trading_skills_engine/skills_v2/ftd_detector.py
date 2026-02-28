from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class FTDDetectorAnalyzer(SkillAnalyzer):
    slug = "ftd-detector"
    _CACHE_REVISION = 2

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        min_index_gain = _to_float(params.get("min_index_gain"), 1.0)
        min_breadth = _to_float(params.get("min_breadth"), 0.55)

        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "min_index_gain": min_index_gain,
                "min_breadth": min_breadth,
                "cache_revision": self._CACHE_REVISION,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        state, source = context.market_provider.load_market_state_with_source()
        source_state = "live" if source == "fmp_live" else "stale"

        breadth_ok = state.breadth_up_ratio >= min_breadth
        index_ok = max(state.spy_return_1d, state.qqq_return_1d, state.iwm_return_1d) >= min_index_gain
        vol_ok = state.vix_level < 25.0
        has_ftd = bool(breadth_ok and index_ok and vol_ok)

        conditions = {
            "breadth_ok": breadth_ok,
            "index_ok": index_ok,
            "volatility_ok": vol_ok,
        }

        base = 42.0
        if breadth_ok:
            base += 20
        if index_ok:
            base += 24
        if vol_ok:
            base += 12
        if has_ftd:
            base += 6

        score = max(0.0, min(100.0, base))
        leaders = sorted(
            state.symbols,
            key=lambda x: (x.momentum_20d * 2.2 + x.daily_return_pct * 1.6 + x.ai_factor * 30.0),
            reverse=True,
        )[:8]
        payload = {
            "has_ftd_signal": has_ftd,
            "score_components": conditions,
            "thresholds": {
                "min_index_gain": min_index_gain,
                "min_breadth": min_breadth,
                "max_vix": 25.0,
            },
            "snapshot": {
                "spy_return_1d": state.spy_return_1d,
                "qqq_return_1d": state.qqq_return_1d,
                "iwm_return_1d": state.iwm_return_1d,
                "breadth_up_ratio": state.breadth_up_ratio,
                "vix_level": state.vix_level,
            },
            "leaders": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "score": round(item.momentum_20d * 2.2 + item.daily_return_pct * 1.6 + item.ai_factor * 30.0, 2),
                    "momentum_20d": round(item.momentum_20d, 2),
                    "daily_return_pct": round(item.daily_return_pct, 2),
                    "ai_factor": round(item.ai_factor, 3),
                }
                for item in leaders
            ],
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=8)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state, score)

    def _build_ok(
        self,
        payload: dict[str, Any],
        cache_info: dict[str, str | None],
        source_state: str,
        score: float | None = None,
    ) -> SkillRunResultV2:
        if score is None:
            conditions = payload.get("score_components", {})
            base = 42.0
            if conditions.get("breadth_ok"):
                base += 20
            if conditions.get("index_ok"):
                base += 24
            if conditions.get("volatility_ok"):
                base += 12
            if payload.get("has_ftd_signal"):
                base += 6
            score = max(0.0, min(100.0, base))

        confidence = 0.69 if source_state == "live" else 0.6
        has_ftd = bool(payload.get("has_ftd_signal"))

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"FTD 신호 {'확인' if has_ftd else '미확인'}",
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
