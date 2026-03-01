from __future__ import annotations

from datetime import date
from pathlib import Path

from trading_skills_engine.ai.contracts import AIReport
from trading_skills_engine.ai.report_service import AIReportService
from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2


def test_orchestrator_history_retention_max_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("SKILL_RUN_HISTORY_MAX_FILES", "2")
    monkeypatch.setenv("SKILL_RUN_HISTORY_MAX_DAYS", "0")

    report_path = tmp_path / "latest_skill_runs_v2.json"
    orchestrator = SkillEngineOrchestratorV2(report_path=report_path)
    orchestrator.market_provider.client = None

    request = EngineRunRequestV2(
        selected_skills=["uptrend-analyzer"],
        as_of_date=date(2026, 2, 26),
    )
    for _ in range(4):
        orchestrator.run_and_persist(request)

    history_files = list((report_path.parent / "history_v2").glob("*.json"))
    assert len(history_files) <= 2


def test_ai_report_history_retention_max_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("AI_REPORT_HISTORY_MAX_FILES", "2")
    monkeypatch.setenv("AI_REPORT_HISTORY_MAX_DAYS", "0")

    source_path = tmp_path / "latest_skill_runs_v2.json"
    ai_path = tmp_path / "latest_ai_report.json"
    service = AIReportService(source_report_path=source_path, ai_report_path=ai_path)

    for idx in range(4):
        service._persist(  # noqa: SLF001
            AIReport(
                status="unavailable",
                portfolio_summary_ko=f"run-{idx}",
                warnings=[],
                error_code="TEST",
            )
        )

    history_files = list((ai_path.parent / "history").glob("*.json"))
    assert len(history_files) <= 2

