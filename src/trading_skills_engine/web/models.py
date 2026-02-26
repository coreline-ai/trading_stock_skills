from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StrategyProfile(str, Enum):
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"


class DashboardHeader(BaseModel):
    app_name: str
    as_of_date: str
    notification_count: int = Field(ge=0)
    user_avatar_url: str


class StrategyWeighting(BaseModel):
    profile: StrategyProfile
    profitability: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    growth: float = Field(ge=0.0, le=1.0)
    auto_rebalance_enabled: bool


class MarketOverview(BaseModel):
    decline_count: int = Field(ge=0)
    neutral_count: int = Field(ge=0)
    growth_count: int = Field(ge=0)


class TopPick(BaseModel):
    symbol: str
    name: str
    sector: str
    return_pct: float
    ai_score_10: float = Field(ge=0.0, le=10.0)
    sparkline_points: list[float]


class FooterNavItem(BaseModel):
    id: str
    label: str
    icon: str
    active: bool


class WorkflowCard(BaseModel):
    workflow_name: str
    exposure_band: str
    portfolio_bias: str
    top_actions: list[str]


class EngineHealth(BaseModel):
    skill_count: int = Field(ge=0)
    avg_score: float = Field(ge=0.0, le=100.0)
    low_score_count: int = Field(ge=0)


class SkillCatalogItem(BaseModel):
    slug: str
    display_name: str
    family: str
    selected: bool


class SkillResultRow(BaseModel):
    skill_slug: str
    status: str
    score_0_100: float = Field(ge=0.0, le=100.0)
    confidence_0_1: float = Field(ge=0.0, le=1.0)
    narrative_ko: str


class DashboardViewModel(BaseModel):
    header: DashboardHeader
    data_source: str
    selected_skills: list[str]
    skill_catalog: list[SkillCatalogItem]
    skill_results: list[SkillResultRow]
    strategy_weighting: StrategyWeighting
    market_overview: MarketOverview
    top_picks: list[TopPick]
    workflows: list[WorkflowCard]
    engine_health: EngineHealth
    footer_nav: list[FooterNavItem]
    risk_badges: list[str]
    date_display_ko: str
