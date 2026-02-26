from __future__ import annotations

from fastapi import APIRouter

from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2, EngineRunResponseV2, SkillCatalogEntryV2
from trading_skills_engine.skills_v2.registry import is_implemented

router = APIRouter(prefix="/api/v2", tags=["engine-v2"])


@router.get("/skills", response_model=list[SkillCatalogEntryV2])
def list_skills_v2() -> list[SkillCatalogEntryV2]:
    return [
        SkillCatalogEntryV2(
            slug=item.slug,
            display_name=item.display_name,
            family=item.family,
            implemented=is_implemented(item.slug),
            uses_llm=item.uses_llm,
            requires_api=item.requires_api,
        )
        for item in SKILL_CATALOG
    ]


@router.post("/skills/run", response_model=EngineRunResponseV2)
def run_skills_v2(payload: EngineRunRequestV2) -> EngineRunResponseV2:
    orchestrator = SkillEngineOrchestratorV2()
    return orchestrator.run_and_persist(payload)


@router.get("/engine/status")
def engine_status_v2() -> dict:
    orchestrator = SkillEngineOrchestratorV2()
    latest = orchestrator.read_latest()
    if not latest:
        return {"ready": False, "message": "No v2 report found"}

    results = latest.get("results") if isinstance(latest.get("results"), list) else []
    ok_count = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "ok")
    unavailable_count = sum(
        1 for item in results if isinstance(item, dict) and item.get("status") == "unavailable"
    )
    not_implemented_count = sum(
        1 for item in results if isinstance(item, dict) and item.get("status") == "not_implemented"
    )

    return {
        "ready": True,
        "run_id": latest.get("run_id"),
        "as_of_date": latest.get("as_of_date"),
        "data_sources": latest.get("data_sources", {}),
        "result_count": len(results),
        "ok_count": ok_count,
        "unavailable_count": unavailable_count,
        "not_implemented_count": not_implemented_count,
    }
