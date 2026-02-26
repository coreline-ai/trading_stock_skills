from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


SkillResultStatus = Literal["ok", "unavailable", "not_implemented"]
DataSourceState = Literal["live", "stale", "unavailable"]


class CacheInfo(BaseModel):
    mode: Literal["fresh", "stale", "none"]
    fetched_at: str | None = None
    expires_at: str | None = None


class SkillRunResultV2(BaseModel):
    skill_slug: str
    status: SkillResultStatus
    score_0_100: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence_0_1: float | None = Field(default=None, ge=0.0, le=1.0)
    summary_ko: str
    reason_code: str | None = None
    cache_info: CacheInfo
    analysis_payload: dict[str, Any]
    source_statuses: dict[str, DataSourceState] = Field(default_factory=dict)


class TopPickV2(BaseModel):
    symbol: str
    reason: str
    score: float


class EngineRunRequestV2(BaseModel):
    selected_skills: list[str] = Field(default_factory=list)
    as_of_date: date | None = None
    params_by_skill: dict[str, dict[str, Any]] = Field(default_factory=dict)


class EngineRunResponseV2(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    as_of_date: str
    data_sources: dict[str, DataSourceState]
    results: list[SkillRunResultV2]
    top_picks: list[TopPickV2]
    warnings: list[str] = Field(default_factory=list)


class SkillCatalogEntryV2(BaseModel):
    slug: str
    display_name: str
    family: str
    implemented: bool
    uses_llm: bool
    requires_api: bool
