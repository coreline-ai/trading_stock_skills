from __future__ import annotations

import hashlib
from statistics import mean

from trading_skills_engine.core.models import MarketState, SkillDefinition, SkillRunResult


def evaluate_skill(skill: SkillDefinition, state: MarketState) -> SkillRunResult:
    base = _base_score(state)
    family_bias = _family_bias(skill.family, state)
    slug_bias = _slug_bias(skill.slug)

    score = _clamp(base + family_bias + slug_bias, 0, 100)
    confidence = _clamp(0.45 + (score / 200), 0.3, 0.95)
    status = _score_to_status(score)
    regime = _derive_regime(state)
    top_candidates = _top_candidates(skill, state, count=5)

    signals = [
        f"breadth_up_ratio={state.breadth_up_ratio:.2f}",
        f"vix={state.vix_level:.1f}",
        f"cross_asset=SPY:{state.spy_return_1d:+.2f}%/QQQ:{state.qqq_return_1d:+.2f}%/IWM:{state.iwm_return_1d:+.2f}%",
    ]

    risk_flags: list[str] = []
    if state.vix_level >= 22:
        risk_flags.append("변동성 확대 구간")
    if state.recession_risk >= 0.45:
        risk_flags.append("매크로 경기둔화 리스크")
    if score < 45:
        risk_flags.append("신호 약세 - 현금 비중 점검")

    invalidation_levels = [
        "SPY 일봉 종가 -2.5% 하회 시 노출 축소",
        "리더 종목 손절 -7% 규칙 적용",
    ]

    narrative_ko = (
        f"{skill.display_name}는 {skill.methodology} 기준으로 점수 {score:.1f}/100을 산출했습니다. "
        f"현재 레짐은 {regime}이며, 상태는 {status}로 분류됩니다."
    )

    return SkillRunResult(
        skill_slug=skill.slug,
        score_0_100=round(score, 2),
        confidence_0_1=round(confidence, 2),
        regime=regime,
        status=status,
        signals=signals,
        risk_flags=risk_flags,
        invalidation_levels=invalidation_levels,
        narrative_ko=narrative_ko,
        top_candidates=top_candidates,
    )


def _base_score(state: MarketState) -> float:
    symbol_momentum = mean(item.momentum_20d for item in state.symbols)
    return (
        50
        + (state.breadth_up_ratio - 0.5) * 60
        - max(0.0, state.vix_level - 18) * 1.6
        - state.recession_risk * 18
        + symbol_momentum * 1.2
    )


def _family_bias(family: str, state: MarketState) -> float:
    if family == "calendar":
        return 6 - state.vix_level * 0.1
    if family == "market_timing":
        return (state.qqq_return_1d - state.iwm_return_1d) * 3
    if family == "screening":
        return state.breadth_up_ratio * 8
    if family == "strategy_risk":
        return 4 - state.recession_risk * 10
    if family == "quality_orchestration":
        return 5
    if family == "edge_research":
        return 3 + state.spy_return_1d
    if family == "earnings_momentum":
        return state.qqq_return_1d * 2.5
    return 0


def _slug_bias(slug: str) -> float:
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    return (seed % 2000) / 100 - 10


def _derive_regime(state: MarketState) -> str:
    if state.recession_risk >= 0.55:
        return "Contraction"
    if state.breadth_up_ratio >= 0.62 and state.spy_return_1d > 0:
        return "Broadening"
    if state.qqq_return_1d > state.iwm_return_1d + 0.5:
        return "Concentration"
    if state.vix_level >= 25:
        return "Transitional"
    return "Balanced"


def _top_candidates(skill: SkillDefinition, state: MarketState, count: int) -> list[str]:
    ranked = sorted(
        state.symbols,
        key=lambda item: _symbol_score_for_skill(skill, item.symbol, item.sector, item.ai_factor, item.momentum_20d, item.daily_return_pct),
        reverse=True,
    )
    if len(ranked) > count:
        offset = _skill_rotation_offset(skill.slug, len(ranked))
        ranked = ranked[offset:] + ranked[:offset]
    return [item.symbol for item in ranked[:count]]


def _symbol_score_for_skill(
    skill: SkillDefinition,
    symbol: str,
    sector: str,
    ai_factor: float,
    momentum_20d: float,
    daily_return_pct: float,
) -> float:
    base = ai_factor * 100 + momentum_20d * 2 + daily_return_pct
    family_boost = _family_sector_boost(skill.family, sector)
    slug_jitter = _pair_jitter(skill.slug, symbol)
    return base + family_boost + slug_jitter


def _family_sector_boost(family: str, sector: str) -> float:
    sector_name = sector.lower()
    if family == "earnings_momentum" and ("tech" in sector_name or "semicon" in sector_name):
        return 7.0
    if family == "market_timing" and ("financial" in sector_name or "energy" in sector_name):
        return 4.0
    if family == "strategy_risk" and ("health" in sector_name or "consumer" in sector_name):
        return 3.5
    if family == "screening" and ("semicon" in sector_name or "technology" in sector_name):
        return 5.0
    if family == "calendar":
        return 2.0
    if family == "edge_research":
        return 1.5
    return 0.0


def _pair_jitter(skill_slug: str, symbol: str) -> float:
    digest = hashlib.sha256(f"{skill_slug}:{symbol}".encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    return (seed % 1200) / 100 - 6


def _skill_rotation_offset(skill_slug: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha256(skill_slug.encode("utf-8")).hexdigest()
    seed = int(digest[8:16], 16)
    # Keep variation bounded to avoid fully random-looking outputs while ensuring
    # selected skill sets can change the final candidate ordering.
    return (seed % min(size - 1, 7)) + 1


def _score_to_status(score: float) -> str:
    if score >= 60:
        return "growth"
    if score >= 45:
        return "neutral"
    return "decline"


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))
