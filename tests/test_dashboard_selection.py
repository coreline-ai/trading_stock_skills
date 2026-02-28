from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from trading_skills_engine.web.app import create_app


def test_dashboard_run_post_redirects(client):
    response = client.post(
        "/dashboard/run",
        data={"recommender_skills": ["market-news-analyst", "us-stock-analysis"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_dashboard_run_writes_two_stage_pipeline_config(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/run",
            data={
                "recommender_skills": ["us-stock-analysis", "market-news-analyst"],
                "analyzer_skills": ["macro-regime-detector"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload.get("pipeline") is not None
    assert payload["pipeline"]["final_intersection"]["policy_used"] in {"all_pass", "pass_or_watch"}
    assert payload["pipeline"]["final_intersection"]["comparison"] == {}
    assert payload["pipeline"]["analysis_targets"]["top10_symbols"] is not None


def test_dashboard_run_two_stage_uses_selected_roles_for_pipeline(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/run",
            data={
                "recommender_skills": ["us-stock-analysis", "market-news-analyst", "scenario-analyzer"],
                "analyzer_skills": ["macro-regime-detector", "us-stock-analysis"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    pipeline = payload.get("pipeline") or {}
    recommender_slugs = [item.get("skill_slug") for item in pipeline.get("recommender_outputs", [])]
    analyzer_slugs = [item.get("skill_slug") for item in pipeline.get("analyzer_outputs", [])]
    assert "us-stock-analysis" in recommender_slugs
    assert "market-news-analyst" in recommender_slugs
    assert "macro-regime-detector" in analyzer_slugs
    assert "scenario-analyzer" not in recommender_slugs
    assert "us-stock-analysis" not in analyzer_slugs


def test_dashboard_run_trims_role_caps(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/run",
            data={
                "recommender_skills": [
                    "us-stock-analysis",
                    "market-news-analyst",
                    "uptrend-analyzer",
                    "market-breadth-analyzer",
                    "vcp-screener",
                    "canslim-screener",
                ],
                "analyzer_skills": [
                    "macro-regime-detector",
                    "market-environment-analysis",
                    "scenario-analyzer",
                    "edge-candidate-agent",
                ],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    pipeline = payload.get("pipeline") or {}
    assert len(pipeline.get("recommender_outputs", [])) <= 5
    assert len(pipeline.get("analyzer_outputs", [])) <= 3


def test_dashboard_run_applies_single_and_multi_ticker_filter(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/run",
            data={
                "recommender_skills": ["vcp-screener"],
                "analyzer_skills": ["macro-regime-detector"],
                "single_ticker": "NVDA",
                "multi_tickers": "AVGO, LLY\nMSFT",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    pipeline = payload.get("pipeline") or {}
    allowed = {"NVDA", "AVGO", "LLY", "MSFT"}
    for output in pipeline.get("recommender_outputs", []):
        for row in output.get("symbols", []):
            assert row.get("symbol") in allowed
    for symbol in pipeline.get("analysis_targets", {}).get("top10_symbols", []):
        assert symbol in allowed


def test_dashboard_ai_report_run_redirects_and_persists_unavailable_when_key_missing(
    tmp_path: Path,
    monkeypatch,
):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/ai-report/run",
            data={},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard?ai_report=missing_key"

    assert ai_report_path.exists()
    payload = json.loads(ai_report_path.read_text(encoding="utf-8"))
    assert payload.get("status") == "unavailable"
    assert payload.get("error_code") == "GLM_API_KEY_MISSING"
