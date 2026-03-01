from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


DecisionLabel = Literal["BUY", "WATCH", "AVOID"]
AIReportStatus = Literal["ok", "unavailable"]
EvidenceSource = Literal["yahoo", "stooq", "fmp", "internal", "zai_search_mcp"]


class EvidenceItem(BaseModel):
    source: EvidenceSource
    url: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class AISymbolDecision(BaseModel):
    symbol: str
    decision: DecisionLabel
    confidence_0_1: float = Field(default=0.5, ge=0.0, le=1.0)
    score_0_100: float = Field(default=50.0, ge=0.0, le=100.0)
    summary_ko: str = ""
    reasons_ko: list[str] = Field(default_factory=list)
    risks_ko: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class AIReport(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    source_run_id: str | None = None
    provider: Literal["glm"] = "glm"
    model: str = "glm-4.5"
    status: AIReportStatus = "ok"
    symbols: list[AISymbolDecision] = Field(default_factory=list)
    portfolio_summary_ko: str = ""
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
