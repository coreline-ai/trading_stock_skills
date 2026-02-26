from __future__ import annotations

from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.base import SkillAnalyzer
from trading_skills_engine.skills_v2.economic_calendar import EconomicCalendarAnalyzer
from trading_skills_engine.skills_v2.earnings_calendar import EarningsCalendarAnalyzer
from trading_skills_engine.skills_v2.market_news import MarketNewsAnalyzer
from trading_skills_engine.skills_v2.us_stock_analysis import USStockAnalysisAnalyzer

_IMPLEMENTED_ANALYZERS: dict[str, SkillAnalyzer] = {
    EconomicCalendarAnalyzer.slug: EconomicCalendarAnalyzer(),
    EarningsCalendarAnalyzer.slug: EarningsCalendarAnalyzer(),
    MarketNewsAnalyzer.slug: MarketNewsAnalyzer(),
    USStockAnalysisAnalyzer.slug: USStockAnalysisAnalyzer(),
}


def get_analyzer(slug: str) -> SkillAnalyzer | None:
    return _IMPLEMENTED_ANALYZERS.get(slug)


def is_implemented(slug: str) -> bool:
    return slug in _IMPLEMENTED_ANALYZERS


def supported_slugs() -> set[str]:
    return set(_IMPLEMENTED_ANALYZERS.keys())


def all_skill_slugs() -> list[str]:
    return [item.slug for item in SKILL_CATALOG]
