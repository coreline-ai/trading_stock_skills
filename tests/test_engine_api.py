from __future__ import annotations


def test_engine_status_endpoint(client):
    response = client.get("/api/v1/engine/status")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body


def test_engine_run_endpoint(client):
    response = client.post("/api/v1/engine/run", json={})
    body = response.json()
    assert response.status_code in {200, 503}
    assert body["status"] in {"ok", "error"}
    if response.status_code == 200:
        assert body["status"] == "ok"
        assert body["skill_count"] == 38
        assert body["avg_score"] >= 0
    else:
        assert body["status"] == "error"
        assert body["data_source"] == "unavailable"
        assert body["skill_count"] == 0
        assert body["failure_reason"]


def test_engine_run_endpoint_with_selected_skills(client):
    response = client.post(
        "/api/v1/engine/run",
        json={"selected_skills": ["market-news-analyst", "us-stock-analysis"]},
    )
    body = response.json()
    assert response.status_code in {200, 503}
    assert body["status"] in {"ok", "error"}
    if response.status_code == 200:
        assert body["selected_count"] == 2
    else:
        assert body["data_source"] == "unavailable"
        assert body["selected_count"] == 2


def test_skills_catalog_endpoint(client):
    response = client.get("/api/v1/skills")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 38
    assert isinstance(body["skills"], list)
    assert body["skills"][0]["slug"]
