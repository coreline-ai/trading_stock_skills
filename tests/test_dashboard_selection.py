from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from trading_skills_engine.core.models import SkillDefinition
from trading_skills_engine.web.app import create_app
from trading_skills_engine.web.services.dashboard_bff_v2 import DashboardBFFV2


def _write_minimal_v2_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": "test-run-for-view-model",
                "as_of_date": "2026-02-28",
                "data_sources": {"fmp": "stale", "rss": "live"},
                "results": [],
                "top_picks": [],
                "pipeline": {},
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_dashboard_bff_v2_skill_detail_fields_present(tmp_path: Path):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    _write_minimal_v2_report(report_path)

    bff = DashboardBFFV2(report_path=report_path)
    model = bff.get_dashboard_view_model()
    assert "universe_meta" in model
    assert model["universe_meta"]["scope"] == "US"

    skills = model["left_menu"]["recommender_skills"] + model["left_menu"]["analyzer_skills"]
    assert skills
    sample = skills[0]

    assert "methodology" in sample
    assert "uses_llm" in sample
    assert "uses_llm_ko" in sample
    assert "requires_api" in sample
    assert "requires_api_ko" in sample
    assert "family_ko" in sample
    assert "role_ko" in sample
    assert "trait_signals" in sample
    assert "trait_axes" in sample
    assert "reference_overview" in sample
    assert "reference_when_to_use" in sample
    assert "reference_data_sources" in sample
    assert "reference_workflow" in sample
    assert "reference_output" in sample
    assert "reference_prerequisites" in sample
    assert "reference_source_url" in sample
    assert isinstance(sample["trait_signals"], list)
    assert isinstance(sample["trait_axes"], dict)

    detail_map = model["skill_detail_map"]
    assert isinstance(detail_map, dict)
    assert sample["slug"] in detail_map
    assert detail_map[sample["slug"]]["slug"] == sample["slug"]
    assert detail_map["weekly-trade-strategy"]["reference_overview"] != ""
    assert detail_map["weekly-trade-strategy"]["reference_workflow"] != ""


def test_dashboard_bff_v2_skill_detail_trait_fallback_defaults(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    _write_minimal_v2_report(report_path)

    monkeypatch.setattr(
        "trading_skills_engine.web.services.dashboard_bff_v2.SKILL_CATALOG",
        [
            SkillDefinition(
                slug="custom-skill",
                display_name="Custom Skill",
                family="screening",
                methodology="custom methodology",
                uses_llm=True,
                requires_api=False,
            )
        ],
    )
    monkeypatch.setattr(
        "trading_skills_engine.web.services.dashboard_bff_v2.get_skill_trait",
        lambda slug: None,
    )

    bff = DashboardBFFV2(report_path=report_path)
    model = bff.get_dashboard_view_model()
    analyzer_skills = model["left_menu"]["analyzer_skills"]

    assert len(analyzer_skills) == 1
    row = analyzer_skills[0]
    assert row["slug"] == "custom-skill"
    assert row["trait_role"] == "analysis_only"
    assert row["role_ko"] == "분석 전용"
    assert row["trait_style"] == "screening"
    assert row["trait_signals"] == []
    assert row["trait_axes"] == {}
    assert row["family_ko"] == "스크리닝"
    assert row["uses_llm_ko"] == "예"
    assert row["requires_api_ko"] == "불필요"
    assert row["reference_overview"] == ""


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
    assert "market-news-analyst" in recommender_slugs
    assert "macro-regime-detector" in analyzer_slugs
    assert "scenario-analyzer" not in recommender_slugs
    assert "us-stock-analysis" not in analyzer_slugs
    # US universe load failure can make us-stock-analysis unavailable in this run.
    if any(item.get("skill_slug") == "us-stock-analysis" and item.get("status") == "ok" for item in payload.get("results", [])):
        assert "us-stock-analysis" in recommender_slugs


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


def test_dashboard_ai_report_run_ignores_stale_running_runtime(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-stale",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": stale_ts,
                "updated_at": stale_ts,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AI_REPORT_RUNNING_TTL_SEC", "600")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    app.state.ai_report_service.api_configured = lambda: True
    app.state.ai_report_service.run_with_runtime = lambda: None

    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/dashboard/ai-report/run",
            data={},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard?ai_report=queued"

    runtime_payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert runtime_payload.get("status") == "failed"
    assert runtime_payload.get("last_error_code") == "AI_REPORT_RUNTIME_STALE"


def test_dashboard_query_notice_queued_shows_status_check_when_ai_is_idle(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-complete-notice",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_report_path.write_text(
        json.dumps(
            {
                "run_id": "ai-ok",
                "created_at": "2026-03-01T04:28:19.915086+00:00",
                "status": "ok",
                "provider": "glm",
                "model": "glm-4.5",
                "symbols": [{"symbol": "NVDA", "decision": "BUY"}],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runtime_path.write_text(
        json.dumps({"status": "idle"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.get("/dashboard?ai_report=queued")
        assert response.status_code == 200
        assert "AI 리포트 상태를 확인 중입니다..." in response.text
        assert "AI 리포트 생성이 완료되었습니다." not in response.text


def test_dashboard_query_notice_completed_shows_completion_message_when_ai_is_idle(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-completed-notice",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_report_path.write_text(
        json.dumps(
            {
                "run_id": "ai-ok",
                "created_at": "2026-03-01T04:28:19.915086+00:00",
                "status": "ok",
                "provider": "glm",
                "model": "glm-4.5",
                "symbols": [{"symbol": "NVDA", "decision": "BUY"}],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runtime_path.write_text(
        json.dumps({"status": "idle"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.get("/dashboard?ai_report=completed")
        assert response.status_code == 200
        assert "AI 리포트 생성이 완료되었습니다." in response.text


def test_dashboard_query_notice_failed_shows_failure_message(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-failed-notice",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_report_path.write_text(
        json.dumps(
            {
                "run_id": "ai-failed",
                "created_at": "2026-03-01T04:28:19.915086+00:00",
                "status": "unavailable",
                "provider": "glm",
                "model": "glm-4.5",
                "symbols": [],
                "warnings": ["GLM_TIMEOUT"],
                "error_code": "GLM_TIMEOUT",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runtime_path.write_text(
        json.dumps({"status": "idle"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.get("/dashboard?ai_report=failed")
        assert response.status_code == 200
        assert "AI 리포트 실행이 종료되었습니다. 실패 상태를 확인해 주세요." in response.text


def test_dashboard_query_notice_queued_shows_pending_when_ai_is_running(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-running-notice",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_report_path.write_text(
        json.dumps(
            {
                "run_id": "ai-prev",
                "created_at": "2026-03-01T04:20:20.709472+00:00",
                "status": "ok",
                "provider": "glm",
                "model": "glm-4.5",
                "symbols": [{"symbol": "NVDA", "decision": "BUY"}],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": now_iso,
                "updated_at": now_iso,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.get("/dashboard?ai_report=queued")
        assert response.status_code == 200
        assert "AI 리포트 생성 요청이 접수되었습니다. 잠시 후 자동 반영됩니다." in response.text


def test_dashboard_query_notice_queued_shows_delay_warning_when_ai_running_too_long(tmp_path: Path, monkeypatch):
    v2_report_path = tmp_path / "latest_skill_runs_v2.json"
    ai_report_path = tmp_path / "latest_ai_report.json"
    runtime_path = tmp_path / "runtime.json"

    v2_report_path.write_text(
        json.dumps(
            {
                "run_id": "run-for-ai-delayed-notice",
                "as_of_date": "2026-02-28",
                "top_picks": [{"symbol": "NVDA", "score": 77.0, "reason": "test"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ai_report_path.write_text(
        json.dumps(
            {
                "run_id": "ai-prev",
                "created_at": "2026-03-01T04:20:20.709472+00:00",
                "status": "ok",
                "provider": "glm",
                "model": "glm-4.5",
                "symbols": [{"symbol": "NVDA", "decision": "BUY"}],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    delayed_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": delayed_iso,
                "updated_at": delayed_iso,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(v2_report_path))
    monkeypatch.setenv("AI_REPORT_PATH", str(ai_report_path))
    monkeypatch.setenv("AI_REPORT_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AI_REPORT_RUNNING_TTL_SEC", "900")
    monkeypatch.setenv("AI_REPORT_RUNNING_DELAY_WARN_SEC", "300")
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.get("/dashboard?ai_report=queued")
        assert response.status_code == 200
        assert "AI 리포트 생성이 지연되고 있습니다" in response.text
