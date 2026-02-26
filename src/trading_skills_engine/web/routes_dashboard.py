from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from trading_skills_engine.web.models import (
    DashboardHeader,
    EngineHealth,
    FooterNavItem,
    MarketOverview,
    SkillCatalogItem,
    SkillResultRow,
    StrategyProfile,
    StrategyWeighting,
    TopPick,
    WorkflowCard,
)
from trading_skills_engine.web.services.dashboard_bff import DashboardBFF

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def get_dashboard_bff(request: Request) -> DashboardBFF:
    return request.app.state.dashboard_bff


@router.get("/header", response_model=DashboardHeader)
def get_dashboard_header(bff: DashboardBFF = Depends(get_dashboard_bff)) -> DashboardHeader:
    return bff.get_header()


@router.get("/strategy-weighting", response_model=StrategyWeighting)
def get_strategy_weighting(
    profile: StrategyProfile = Query(default=StrategyProfile.BALANCED),
    bff: DashboardBFF = Depends(get_dashboard_bff),
) -> StrategyWeighting:
    return bff.get_strategy_weighting(profile=profile)


@router.get("/market-overview", response_model=MarketOverview)
def get_market_overview(bff: DashboardBFF = Depends(get_dashboard_bff)) -> MarketOverview:
    return bff.get_market_overview()


@router.get("/top-picks", response_model=list[TopPick])
def get_top_picks(
    limit: int = Query(default=5, ge=1, le=20),
    bff: DashboardBFF = Depends(get_dashboard_bff),
) -> list[TopPick]:
    return bff.get_top_picks(limit=limit)


@router.get("/footer-nav", response_model=list[FooterNavItem])
def get_footer_nav() -> list[FooterNavItem]:
    return DashboardBFF.get_footer_nav()


@router.get("/skills", response_model=list[SkillCatalogItem])
def get_skills(bff: DashboardBFF = Depends(get_dashboard_bff)) -> list[SkillCatalogItem]:
    return bff.get_skill_catalog()


@router.get("/skill-results", response_model=list[SkillResultRow])
def get_skill_results(
    limit: int = Query(default=50, ge=1, le=200),
    bff: DashboardBFF = Depends(get_dashboard_bff),
) -> list[SkillResultRow]:
    return bff.get_skill_results(limit=limit)


@router.get("/workflows", response_model=list[WorkflowCard])
def get_workflows(bff: DashboardBFF = Depends(get_dashboard_bff)) -> list[WorkflowCard]:
    return bff.get_workflows()


@router.get("/engine-health", response_model=EngineHealth)
def get_engine_health(bff: DashboardBFF = Depends(get_dashboard_bff)) -> EngineHealth:
    return bff.get_engine_health()
