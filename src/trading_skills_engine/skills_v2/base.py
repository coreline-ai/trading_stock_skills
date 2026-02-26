from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.data.fmp_calendar_client import FMPCalendarClient
from trading_skills_engine.data.fmp_news_client import FMPNewsClient
from trading_skills_engine.data.provider import MarketDataProvider
from trading_skills_engine.data.rss_client import RSSClient
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


@dataclass
class AnalyzerContext:
    as_of_date: date
    cache_store: CacheStore
    market_provider: MarketDataProvider
    fmp_calendar: FMPCalendarClient | None
    fmp_news: FMPNewsClient | None
    rss_client: RSSClient
    warnings: list[str] = field(default_factory=list)


class SkillAnalyzer(Protocol):
    slug: str

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        ...


def unavailable_result(
    skill_slug: str,
    summary_ko: str,
    reason_code: str,
    cache_info: CacheInfo | None = None,
    source_statuses: dict[str, str] | None = None,
) -> SkillRunResultV2:
    return SkillRunResultV2(
        skill_slug=skill_slug,
        status="unavailable",
        score_0_100=None,
        confidence_0_1=None,
        summary_ko=summary_ko,
        reason_code=reason_code,
        cache_info=cache_info or CacheInfo(mode="none"),
        analysis_payload={},
        source_statuses=source_statuses or {},
    )


def not_implemented_result(skill_slug: str) -> SkillRunResultV2:
    return SkillRunResultV2(
        skill_slug=skill_slug,
        status="not_implemented",
        score_0_100=None,
        confidence_0_1=None,
        summary_ko="v2에서 아직 구현되지 않은 스킬입니다.",
        reason_code="NOT_IMPLEMENTED",
        cache_info=CacheInfo(mode="none"),
        analysis_payload={},
        source_statuses={},
    )
