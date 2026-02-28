from __future__ import annotations

from typing import Literal

from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.base import SkillAnalyzer
from trading_skills_engine.skills_v2.earnings_trade import EarningsTradeAnalyzer
from trading_skills_engine.skills_v2.economic_calendar import EconomicCalendarAnalyzer
from trading_skills_engine.skills_v2.earnings_calendar import EarningsCalendarAnalyzer
from trading_skills_engine.skills_v2.ftd_detector import FTDDetectorAnalyzer
from trading_skills_engine.skills_v2.market_breadth import MarketBreadthAnalyzer
from trading_skills_engine.skills_v2.market_news import MarketNewsAnalyzer
from trading_skills_engine.skills_v2.market_top_detector import MarketTopDetectorAnalyzer
from trading_skills_engine.skills_v2.portfolio_manager import PortfolioManagerAnalyzer
from trading_skills_engine.skills_v2.proxy import build_proxy_analyzers
from trading_skills_engine.skills_v2.traits import is_recommendation_capable as _trait_recommendation_capable
from trading_skills_engine.skills_v2.uptrend import UptrendAnalyzer
from trading_skills_engine.skills_v2.us_stock_analysis import USStockAnalysisAnalyzer

_CORE_IMPLEMENTED_ANALYZERS: dict[str, SkillAnalyzer] = {
    EconomicCalendarAnalyzer.slug: EconomicCalendarAnalyzer(),
    EarningsCalendarAnalyzer.slug: EarningsCalendarAnalyzer(),
    MarketNewsAnalyzer.slug: MarketNewsAnalyzer(),
    USStockAnalysisAnalyzer.slug: USStockAnalysisAnalyzer(),
    MarketBreadthAnalyzer.slug: MarketBreadthAnalyzer(),
    UptrendAnalyzer.slug: UptrendAnalyzer(),
    MarketTopDetectorAnalyzer.slug: MarketTopDetectorAnalyzer(),
    FTDDetectorAnalyzer.slug: FTDDetectorAnalyzer(),
    EarningsTradeAnalyzer.slug: EarningsTradeAnalyzer(),
    PortfolioManagerAnalyzer.slug: PortfolioManagerAnalyzer(),
}
_PROXY_IMPLEMENTED_ANALYZERS = build_proxy_analyzers(set(_CORE_IMPLEMENTED_ANALYZERS.keys()))
_IMPLEMENTED_ANALYZERS: dict[str, SkillAnalyzer] = {
    **_CORE_IMPLEMENTED_ANALYZERS,
    **_PROXY_IMPLEMENTED_ANALYZERS,
}


def get_analyzer(slug: str) -> SkillAnalyzer | None:
    return _IMPLEMENTED_ANALYZERS.get(slug)


def is_implemented(slug: str) -> bool:
    return slug in _IMPLEMENTED_ANALYZERS


def supported_slugs() -> set[str]:
    return set(_IMPLEMENTED_ANALYZERS.keys())


def all_skill_slugs() -> list[str]:
    return [item.slug for item in SKILL_CATALOG]


def is_recommendation_capable(slug: str, mode: Literal["skill_consensus", "watchlist_consensus"] = "skill_consensus") -> bool:
    del mode
    analyzer = get_analyzer(slug)
    if analyzer is None:
        return False

    return _trait_recommendation_capable(slug)
