from __future__ import annotations

from pathlib import Path

from trading_skills_engine.engine.orchestrator import SkillEngineOrchestrator
from trading_skills_engine.skills.catalog import skill_count


def test_orchestrator_runs_all_38_skills():
    orchestrator = SkillEngineOrchestrator()
    report = orchestrator.run_all_skills()

    assert report["skill_count"] == 38
    assert report["skill_count"] == skill_count()
    assert len(report["skill_runs"]) == 38
    assert len(report["workflows"]) >= 3
    assert len(report["top_picks"]) == 5


def test_orchestrator_writes_report(tmp_path: Path):
    orchestrator = SkillEngineOrchestrator()
    output_path = tmp_path / "skill_runs.json"

    report = orchestrator.write_report(output_path)

    assert output_path.exists()
    assert report["skill_count"] == 38


def test_orchestrator_runs_selected_skills_only():
    orchestrator = SkillEngineOrchestrator()
    report = orchestrator.run_all_skills(selected_slugs=["market-news-analyst", "us-stock-analysis"])
    assert report["skill_count"] == 2
    assert set(report["selected_skills"]) == {"market-news-analyst", "us-stock-analysis"}


def test_top_picks_change_when_skill_selection_changes():
    orchestrator = SkillEngineOrchestrator()
    report_a = orchestrator.run_all_skills(selected_slugs=["market-news-analyst"])
    report_b = orchestrator.run_all_skills(selected_slugs=["vcp-screener"])

    picks_a = [item["symbol"] for item in report_a["top_picks"]]
    picks_b = [item["symbol"] for item in report_b["top_picks"]]
    assert picks_a != picks_b
