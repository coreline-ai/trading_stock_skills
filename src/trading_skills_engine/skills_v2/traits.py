from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trading_skills_engine.skills.catalog import SKILL_CATALOG

RecommendationRole = Literal["direct", "candidate", "analysis_only"]


@dataclass(frozen=True)
class SkillTrait:
    slug: str
    family: str
    style: str
    recommendation_role: RecommendationRole
    axis_weights: dict[str, float]
    signals: tuple[str, ...]
    consensus_weight: float


_FAMILY_DEFAULTS: dict[str, dict[str, object]] = {
    "market_analysis": {
        "style": "market_structure",
        "recommendation_role": "candidate",
        "axis_weights": {"trend_score": 0.4, "quality_score": 0.35, "stability_score": 0.25},
        "signals": ("breadth_sensitive", "risk_on"),
        "consensus_weight": 1.0,
    },
    "calendar": {
        "style": "event_risk",
        "recommendation_role": "candidate",
        "axis_weights": {"stability_score": 0.45, "defensive_score": 0.35, "trend_score": 0.2},
        "signals": ("event_driven", "risk_off"),
        "consensus_weight": 0.9,
    },
    "strategy_risk": {
        "style": "allocation",
        "recommendation_role": "analysis_only",
        "axis_weights": {"defensive_score": 0.45, "quality_score": 0.35, "value_score": 0.2},
        "signals": ("risk_off",),
        "consensus_weight": 0.7,
    },
    "market_timing": {
        "style": "timing",
        "recommendation_role": "candidate",
        "axis_weights": {"breakout_score": 0.45, "trend_score": 0.35, "stability_score": 0.2},
        "signals": ("breadth_sensitive", "risk_on"),
        "consensus_weight": 1.05,
    },
    "earnings_momentum": {
        "style": "earnings_momentum",
        "recommendation_role": "direct",
        "axis_weights": {"breakout_score": 0.5, "quality_score": 0.3, "trend_score": 0.2},
        "signals": ("event_driven", "risk_on"),
        "consensus_weight": 1.1,
    },
    "screening": {
        "style": "screening",
        "recommendation_role": "direct",
        "axis_weights": {"quality_score": 0.35, "trend_score": 0.3, "value_score": 0.2, "stability_score": 0.15},
        "signals": ("breadth_sensitive",),
        "consensus_weight": 1.0,
    },
    "edge_research": {
        "style": "edge_research",
        "recommendation_role": "analysis_only",
        "axis_weights": {"quality_score": 0.45, "value_score": 0.3, "stability_score": 0.25},
        "signals": ("risk_neutral",),
        "consensus_weight": 0.65,
    },
    "quality_orchestration": {
        "style": "orchestration",
        "recommendation_role": "analysis_only",
        "axis_weights": {"stability_score": 0.5, "quality_score": 0.3, "defensive_score": 0.2},
        "signals": ("risk_neutral",),
        "consensus_weight": 0.6,
    },
}

# Slug-level overrides provide 1:1 trait intent per skill.
_SLUG_OVERRIDES: dict[str, dict[str, object]] = {
    # market_analysis
    "sector-analyst": {
        "style": "sector_rotation",
        "axis_weights": {"trend_score": 0.45, "quality_score": 0.25, "value_score": 0.3},
        "signals": ("breadth_sensitive", "risk_on"),
    },
    "breadth-chart-analyst": {
        "style": "breadth_phase",
        "axis_weights": {"trend_score": 0.5, "stability_score": 0.25, "quality_score": 0.25},
        "signals": ("breadth_sensitive",),
    },
    "technical-analyst": {
        "style": "technical_invalidation",
        "axis_weights": {"breakout_score": 0.45, "trend_score": 0.35, "stability_score": 0.2},
    },
    "market-news-analyst": {
        "style": "news_impact",
        "recommendation_role": "direct",
        "consensus_weight": 1.15,
        "signals": ("event_driven", "risk_on"),
    },
    "us-stock-analysis": {
        "style": "single_stock_memo",
        "recommendation_role": "direct",
        "consensus_weight": 1.2,
        "axis_weights": {"quality_score": 0.4, "trend_score": 0.3, "stability_score": 0.3},
    },
    "market-environment-analysis": {
        "style": "cross_asset_regime",
        "recommendation_role": "analysis_only",
        "consensus_weight": 0.75,
        "axis_weights": {"defensive_score": 0.5, "stability_score": 0.35, "value_score": 0.15},
        "signals": ("rate_sensitive", "risk_off", "breadth_sensitive"),
    },
    "market-breadth-analyzer": {
        "style": "breadth_factor",
        "axis_weights": {"trend_score": 0.55, "stability_score": 0.3, "quality_score": 0.15},
    },
    "uptrend-analyzer": {
        "style": "trend_participation",
        "axis_weights": {"trend_score": 0.5, "breakout_score": 0.3, "quality_score": 0.2},
        "consensus_weight": 1.1,
    },
    "macro-regime-detector": {
        "style": "macro_regime",
        "recommendation_role": "analysis_only",
        "axis_weights": {"trend_score": 0.45, "breakout_score": 0.3, "quality_score": 0.25},
        "signals": ("rate_sensitive", "event_driven", "risk_on"),
        "consensus_weight": 0.8,
    },
    "institutional-flow-tracker": {
        "style": "smart_money_flow",
        "axis_weights": {"quality_score": 0.4, "trend_score": 0.35, "stability_score": 0.25},
    },
    "theme-detector": {
        "style": "theme_maturity",
        "axis_weights": {"trend_score": 0.35, "breakout_score": 0.35, "quality_score": 0.3},
    },
    # calendar
    "economic-calendar-fetcher": {
        "style": "macro_event_window",
        "recommendation_role": "analysis_only",
        "consensus_weight": 0.7,
        "signals": ("event_driven", "rate_sensitive", "risk_off"),
    },
    "earnings-calendar": {
        "style": "earnings_schedule",
        "recommendation_role": "direct",
        "consensus_weight": 1.1,
        "axis_weights": {"quality_score": 0.35, "breakout_score": 0.35, "stability_score": 0.3},
    },
    # strategy_risk
    "scenario-analyzer": {"style": "scenario_matrix"},
    "backtest-expert": {"style": "robustness_test", "consensus_weight": 0.65},
    "stanley-druckenmiller-investment": {
        "style": "macro_conviction",
        "axis_weights": {"trend_score": 0.3, "quality_score": 0.3, "defensive_score": 0.4},
    },
    "us-market-bubble-detector": {
        "style": "bubble_risk",
        "axis_weights": {"defensive_score": 0.5, "stability_score": 0.35, "value_score": 0.15},
    },
    "options-strategy-advisor": {
        "style": "options_payoff",
        "axis_weights": {"stability_score": 0.5, "defensive_score": 0.3, "trend_score": 0.2},
    },
    "portfolio-manager": {
        "style": "allocation_rebalance",
        "recommendation_role": "direct",
        "consensus_weight": 1.0,
        "axis_weights": {"quality_score": 0.35, "defensive_score": 0.35, "stability_score": 0.3},
    },
    "strategy-pivot-designer": {"style": "strategy_pivot", "consensus_weight": 0.65},
    # market_timing
    "market-top-detector": {
        "style": "distribution_days",
        "axis_weights": {"defensive_score": 0.45, "stability_score": 0.35, "trend_score": 0.2},
        "signals": ("breadth_sensitive", "risk_off"),
    },
    "ftd-detector": {
        "style": "follow_through_day",
        "axis_weights": {"breakout_score": 0.5, "trend_score": 0.3, "stability_score": 0.2},
        "consensus_weight": 1.1,
        "signals": ("breadth_sensitive", "risk_on"),
    },
    # earnings_momentum
    "earnings-trade-analyzer": {
        "style": "post_earnings_gap",
        "recommendation_role": "direct",
        "consensus_weight": 1.2,
    },
    "pead-screener": {
        "style": "pead_stages",
        "recommendation_role": "direct",
        "consensus_weight": 1.15,
        "axis_weights": {"breakout_score": 0.45, "quality_score": 0.35, "trend_score": 0.2},
    },
    # screening
    "vcp-screener": {
        "style": "vcp_pattern",
        "axis_weights": {"breakout_score": 0.45, "trend_score": 0.35, "quality_score": 0.2},
        "consensus_weight": 1.1,
    },
    "canslim-screener": {
        "style": "canslim_factors",
        "axis_weights": {"quality_score": 0.35, "breakout_score": 0.35, "trend_score": 0.3},
        "consensus_weight": 1.1,
    },
    "value-dividend-screener": {
        "style": "value_income",
        "axis_weights": {"value_score": 0.45, "defensive_score": 0.3, "quality_score": 0.25},
        "signals": ("risk_off", "income_focus"),
    },
    "dividend-growth-pullback-screener": {
        "style": "dividend_pullback",
        "axis_weights": {"oversold_score": 0.35, "value_score": 0.35, "quality_score": 0.3},
        "signals": ("income_focus", "risk_neutral"),
    },
    "kanchi-dividend-sop": {
        "style": "dividend_sop",
        "axis_weights": {"value_score": 0.4, "defensive_score": 0.35, "quality_score": 0.25},
    },
    "kanchi-dividend-review-monitor": {
        "style": "dividend_review_monitor",
        "recommendation_role": "analysis_only",
        "consensus_weight": 0.7,
        "axis_weights": {"stability_score": 0.45, "defensive_score": 0.35, "quality_score": 0.2},
    },
    "kanchi-dividend-us-tax-accounting": {
        "style": "tax_accounting",
        "recommendation_role": "analysis_only",
        "consensus_weight": 0.6,
        "axis_weights": {"defensive_score": 0.4, "stability_score": 0.4, "value_score": 0.2},
    },
    "pair-trade-screener": {
        "style": "cointegration_reversion",
        "axis_weights": {"oversold_score": 0.5, "value_score": 0.3, "stability_score": 0.2},
        "signals": ("risk_neutral",),
    },
    # edge_research
    "edge-candidate-agent": {"style": "edge_ticketing", "consensus_weight": 0.65},
    "edge-concept-synthesizer": {"style": "edge_concepts", "consensus_weight": 0.65},
    "edge-hint-extractor": {"style": "edge_hints", "consensus_weight": 0.65},
    "edge-strategy-designer": {"style": "edge_strategy_design", "consensus_weight": 0.65},
    # quality_orchestration
    "dual-axis-skill-reviewer": {"style": "dual_axis_review", "consensus_weight": 0.6},
    "weekly-trade-strategy": {
        "style": "multi_skill_chain",
        "recommendation_role": "candidate",
        "consensus_weight": 0.9,
        "axis_weights": {"trend_score": 0.3, "quality_score": 0.3, "stability_score": 0.4},
    },
}


_SKILL_TRAITS: dict[str, SkillTrait] = {}
for definition in SKILL_CATALOG:
    family_base = _FAMILY_DEFAULTS.get(definition.family)
    if family_base is None:
        continue

    merged: dict[str, object] = dict(family_base)
    merged.update(_SLUG_OVERRIDES.get(definition.slug, {}))

    axis_weights = dict(merged.get("axis_weights") or {})
    weight_sum = sum(float(value) for value in axis_weights.values())
    if weight_sum <= 0:
        axis_weights = {"trend_score": 0.5, "quality_score": 0.5}
        weight_sum = 1.0
    normalized_axis_weights = {
        axis: round(float(weight) / weight_sum, 4)
        for axis, weight in axis_weights.items()
    }

    role_value = str(merged.get("recommendation_role") or "analysis_only")
    if role_value not in {"direct", "candidate", "analysis_only"}:
        role_value = "analysis_only"

    _SKILL_TRAITS[definition.slug] = SkillTrait(
        slug=definition.slug,
        family=definition.family,
        style=str(merged.get("style") or definition.family),
        recommendation_role=role_value,  # type: ignore[arg-type]
        axis_weights=normalized_axis_weights,
        signals=tuple(str(item) for item in (merged.get("signals") or ())),
        consensus_weight=float(merged.get("consensus_weight") or 1.0),
    )


def get_skill_trait(slug: str) -> SkillTrait | None:
    return _SKILL_TRAITS.get(slug)


def all_skill_traits() -> dict[str, SkillTrait]:
    return dict(_SKILL_TRAITS)


def is_recommendation_capable(slug: str) -> bool:
    trait = get_skill_trait(slug)
    if trait is None:
        return False
    return trait.recommendation_role in {"direct", "candidate"}
