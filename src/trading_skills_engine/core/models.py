from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

SkillFamily = Literal[
    "market_analysis",
    "calendar",
    "strategy_risk",
    "market_timing",
    "earnings_momentum",
    "screening",
    "quality_orchestration",
    "edge_research",
]


@dataclass(frozen=True)
class SkillDefinition:
    slug: str
    display_name: str
    family: SkillFamily
    methodology: str
    uses_llm: bool
    requires_api: bool


@dataclass(frozen=True)
class SymbolSignal:
    symbol: str
    name: str
    sector: str
    daily_return_pct: float
    momentum_20d: float
    ai_factor: float


@dataclass(frozen=True)
class MarketState:
    as_of_date: date
    spy_return_1d: float
    qqq_return_1d: float
    iwm_return_1d: float
    tlt_return_1d: float
    vix_level: float
    breadth_up_ratio: float
    recession_risk: float
    symbols: list[SymbolSignal]


@dataclass(frozen=True)
class SkillRunResult:
    skill_slug: str
    score_0_100: float
    confidence_0_1: float
    regime: str
    status: Literal["growth", "neutral", "decline"]
    signals: list[str]
    risk_flags: list[str]
    invalidation_levels: list[str]
    narrative_ko: str
    top_candidates: list[str]


@dataclass(frozen=True)
class WorkflowResult:
    workflow_name: str
    exposure_band: str
    portfolio_bias: str
    top_actions: list[str]
    contributing_skills: list[str]
