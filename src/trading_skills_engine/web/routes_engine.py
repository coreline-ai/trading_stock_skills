from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from trading_skills_engine.engine.orchestrator import SkillEngineOrchestrator
from trading_skills_engine.skills.catalog import SKILL_CATALOG

router = APIRouter(prefix="/api/v1", tags=["engine"])


class EngineRunRequest(BaseModel):
    selected_skills: list[str] = Field(default_factory=list)


@router.get("/skills")
def list_skills() -> dict:
    return {
        "count": len(SKILL_CATALOG),
        "skills": [
            {
                "slug": item.slug,
                "display_name": item.display_name,
                "family": item.family,
                "uses_llm": item.uses_llm,
                "requires_api": item.requires_api,
            }
            for item in SKILL_CATALOG
        ],
    }


@router.post("/engine/run")
def run_engine(payload: EngineRunRequest) -> dict:
    orchestrator = SkillEngineOrchestrator()
    report_path = Path("reports/skill_runs/latest_skill_runs.json")
    report = orchestrator.write_report(report_path, selected_slugs=payload.selected_skills or None)

    snapshot = {
        "app_name": report["app_name"],
        "as_of_date": report["as_of_date"],
        "notification_count": report["notification_count"],
        "auto_rebalance_enabled": report["auto_rebalance_enabled"],
        "strategy_profiles": report["strategy_profiles"],
        "skill_classification_counts": report["skill_classification_counts"],
        "top_picks": report["top_picks"],
        "data_source": report.get("data_source", "unavailable"),
        "selected_skills": report.get("selected_skills", []),
    }

    snapshot_path = Path("reports/eod/latest_snapshot.json")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    response_payload = {
        "status": "ok",
        "skill_count": report["skill_count"],
        "selected_count": len(report.get("selected_skills", [])),
        "data_source": report.get("data_source", "unavailable"),
        "report_path": str(report_path),
        "snapshot_path": str(snapshot_path),
        "avg_score": report["quality_summary"]["avg_score"],
        "failure_reason": report.get("failure_reason", ""),
    }
    if report.get("data_source") == "unavailable":
        response_payload["status"] = "error"
        return JSONResponse(status_code=503, content=response_payload)
    return response_payload


@router.get("/engine/status")
def engine_status() -> dict:
    report_path = Path("reports/skill_runs/latest_skill_runs.json")
    if not report_path.exists():
        return {"ready": False, "message": "No skill run report found"}

    data = json.loads(report_path.read_text(encoding="utf-8"))
    selected = data.get("selected_skills") if isinstance(data.get("selected_skills"), list) else []
    return {
        "ready": True,
        "as_of_date": data.get("as_of_date"),
        "skill_count": data.get("skill_count", 0),
        "selected_count": len(selected),
        "data_source": data.get("data_source", "unavailable"),
        "avg_score": data.get("quality_summary", {}).get("avg_score", 0),
    }
