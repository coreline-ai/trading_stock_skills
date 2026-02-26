from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from trading_skills_engine.web.app import create_app


def test_v2_skills_catalog_contract(client):
    response = client.get("/api/v2/skills")
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 38

    first = body[0]
    assert set(first.keys()) == {
        "slug",
        "display_name",
        "family",
        "implemented",
        "uses_llm",
        "requires_api",
    }
    assert isinstance(first["implemented"], bool)


def test_v2_engine_run_contract(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "economic-calendar-fetcher",
                "earnings-calendar",
                "market-news-analyst",
                "us-stock-analysis",
            ],
            "as_of_date": "2026-02-26",
            "params_by_skill": {
                "economic-calendar-fetcher": {"from_days": 7, "to_days": 90, "country": "US"},
                "earnings-calendar": {"days": 7, "min_market_cap": 2000000000},
                "market-news-analyst": {"lookback_days": 10, "max_items": 80},
                "us-stock-analysis": {"ticker": "AAPL"},
            },
        },
    )
    assert response.status_code == 200

    body = response.json()
    assert set(body.keys()) == {"run_id", "as_of_date", "data_sources", "results", "top_picks", "warnings"}
    assert body["as_of_date"] == "2026-02-26"
    assert set(body["data_sources"].keys()) == {"fmp", "rss"}
    assert len(body["results"]) == 4

    for item in body["results"]:
        assert set(item.keys()) == {
            "skill_slug",
            "status",
            "score_0_100",
            "confidence_0_1",
            "summary_ko",
            "reason_code",
            "cache_info",
            "analysis_payload",
            "source_statuses",
        }
        assert item["status"] in {"ok", "unavailable", "not_implemented"}


def test_v2_not_implemented_status(client):
    response = client.post(
        "/api/v2/skills/run",
        json={"selected_skills": ["vcp-screener"], "as_of_date": "2026-02-26"},
    )
    assert response.status_code == 200

    result = response.json()["results"][0]
    assert result["skill_slug"] == "vcp-screener"
    assert result["status"] == "not_implemented"
    assert result["score_0_100"] is None
    assert result["confidence_0_1"] is None


def test_dashboard_run_renders_not_implemented(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        run_response = isolated_client.post(
            "/dashboard/run",
            data={"skills": ["vcp-screener"]},
            follow_redirects=False,
        )
        assert run_response.status_code == 303
        assert run_response.headers["location"] == "/dashboard"

        page = isolated_client.get("/dashboard")
        assert page.status_code == 200
        assert "vcp-screener" in page.text
        assert "not_implemented" in page.text
