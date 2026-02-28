from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class MarketTopDetectorAnalyzer(SkillAnalyzer):
    slug = "market-top-detector"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        vix_alert = _to_float(params.get("vix_alert"), 24.0)
        breadth_floor = _to_float(params.get("breadth_floor"), 0.52)

        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "vix_alert": vix_alert,
                "breadth_floor": breadth_floor,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        state, source = context.market_provider.load_market_state_with_source()
        source_state = "live" if source == "fmp_live" else "stale"

        signals: list[str] = []
        risk_points = 0.0

        if state.vix_level >= vix_alert:
            risk_points += 28
            signals.append(f"VIX 고점 경고 ({state.vix_level:.1f} >= {vix_alert:.1f})")
        if state.breadth_up_ratio < breadth_floor:
            risk_points += 26
            signals.append(f"Breadth 약화 ({state.breadth_up_ratio:.2f} < {breadth_floor:.2f})")
        if state.spy_return_1d < 0 and state.qqq_return_1d < 0:
            risk_points += 18
            signals.append("SPY/QQQ 동반 하락")
        if state.qqq_return_1d - state.iwm_return_1d > 1.2:
            risk_points += 14
            signals.append("대형주 쏠림 심화")
        if state.recession_risk >= 0.45:
            risk_points += 14
            signals.append("매크로 경기둔화 경고")

        risk_points = max(0.0, min(100.0, risk_points))
        safety_score = round(100.0 - risk_points, 2)

        payload = {
            "top_risk_score_0_100": round(risk_points, 2),
            "safety_score_0_100": safety_score,
            "risk_level": _risk_level(risk_points),
            "signals": signals,
            "snapshot": {
                "spy_return_1d": state.spy_return_1d,
                "qqq_return_1d": state.qqq_return_1d,
                "iwm_return_1d": state.iwm_return_1d,
                "vix_level": state.vix_level,
                "breadth_up_ratio": state.breadth_up_ratio,
                "recession_risk": state.recession_risk,
            },
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=8)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state)

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], source_state: str) -> SkillRunResultV2:
        safety = _to_float(payload.get("safety_score_0_100"), 50.0)
        confidence = 0.71 if source_state == "live" else 0.63

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(safety, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=(
                f"시장 상단 리스크 {payload.get('risk_level')} "
                f"(risk {payload.get('top_risk_score_0_100', 0):.1f})"
            ),
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def _risk_level(score: float) -> str:
    if score >= 65:
        return "높음"
    if score >= 40:
        return "중간"
    return "낮음"


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"
