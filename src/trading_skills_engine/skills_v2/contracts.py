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
    decision: Literal["PASS", "WATCH", "REJECT"] | None = None
    primary_skill: str | None = None
    confirm_votes: int | None = None
    confirm_required: int | None = None
    veto_count: int | None = None
    confirm_hits: list[str] = Field(default_factory=list)
    veto_skills: list[str] = Field(default_factory=list)


class PipelineConfigV2(BaseModel):
    recommender_skills: list[str] = Field(default_factory=list)
    analyzer_skills: list[str] = Field(default_factory=list)
    recommender_top_n: int = Field(default=25, ge=5, le=50)
    intersection_policy: Literal["strict"] = "strict"
    analyzer_pass_policy: Literal["all_pass", "pass_or_watch"] = "all_pass"
    comparison_mode: bool = False


class RecommenderSymbolV2(BaseModel):
    symbol: str
    rank: int
    percentile: float
    raw_score: float
    reason: str


class RecommenderOutputV2(BaseModel):
    skill_slug: str
    symbols: list[RecommenderSymbolV2] = Field(default_factory=list)


class RecommenderIntersectionV2(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    support_count_by_symbol: dict[str, int] = Field(default_factory=dict)
    dropped_by_stage: list[str] = Field(default_factory=list)


class AnalyzerEvaluationV2(BaseModel):
    symbol: str
    source_recommender: str | None = None
    target_group: Literal["intersection", "top10"] | None = None
    decision: Literal["PASS", "WATCH", "REJECT"]
    score: float
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class AnalyzerOutputV2(BaseModel):
    skill_slug: str
    evaluations: list[AnalyzerEvaluationV2] = Field(default_factory=list)


class AnalyzerOutputByTargetV2(BaseModel):
    skill_slug: str
    target_group: Literal["intersection", "top10"]
    evaluations: list[AnalyzerEvaluationV2] = Field(default_factory=list)


class FinalIntersectionV2(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    final_reasons: list[str] = Field(default_factory=list)
    policy_used: Literal["all_pass", "pass_or_watch"] = "all_pass"
    comparison: dict[str, Any] = Field(default_factory=dict)
    post_analyzer_by_recommender: list[dict[str, Any]] = Field(default_factory=list)
    per_skill_traces: list[dict[str, Any]] = Field(default_factory=list)
    ranking: list[dict[str, Any]] = Field(default_factory=list)


class RecommenderUnionTop10V2(BaseModel):
    symbols: list[dict[str, Any]] = Field(default_factory=list)
    source_union_count: int = 0


class AnalysisTargetsV2(BaseModel):
    intersection_symbols: list[str] = Field(default_factory=list)
    top10_symbols: list[str] = Field(default_factory=list)


class FinalSummaryV2(BaseModel):
    intersection_symbols: list[str] = Field(default_factory=list)
    top5_from_top10: list[dict[str, Any]] = Field(default_factory=list)
    policy_used: Literal["all_pass", "pass_or_watch"] = "all_pass"
    dropped_by_stage: list[str] = Field(default_factory=list)


class PipelineResultV2(BaseModel):
    recommender_outputs: list[RecommenderOutputV2] = Field(default_factory=list)
    recommender_intersection: RecommenderIntersectionV2 = Field(default_factory=RecommenderIntersectionV2)
    recommender_union_top10: RecommenderUnionTop10V2 = Field(default_factory=RecommenderUnionTop10V2)
    analysis_targets: AnalysisTargetsV2 = Field(default_factory=AnalysisTargetsV2)
    analyzer_outputs: list[AnalyzerOutputV2] = Field(default_factory=list)
    analyzer_outputs_by_target: list[AnalyzerOutputByTargetV2] = Field(default_factory=list)
    final_intersection: FinalIntersectionV2 = Field(default_factory=FinalIntersectionV2)
    final_summary: FinalSummaryV2 = Field(default_factory=FinalSummaryV2)


class EngineRunRequestV2(BaseModel):
    selected_skills: list[str] = Field(default_factory=list)
    as_of_date: date | None = None
    params_by_skill: dict[str, dict[str, Any]] = Field(default_factory=dict)
    top_picks_mode: Literal["skill_consensus", "watchlist_consensus", "role_gated_consensus", "two_stage_intersection"] = "skill_consensus"
    watchlist_symbols: list[str] = Field(default_factory=list)
    top_picks_limit: int = Field(default=5, ge=1, le=50)
    pipeline_config: PipelineConfigV2 | None = None


class EngineRunResponseV2(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    as_of_date: str
    data_sources: dict[str, DataSourceState]
    results: list[SkillRunResultV2]
    top_picks: list[TopPickV2]
    pipeline: PipelineResultV2 | None = None
    warnings: list[str] = Field(default_factory=list)


class SkillCatalogEntryV2(BaseModel):
    slug: str
    display_name: str
    family: str
    implemented: bool
    uses_llm: bool
    requires_api: bool
