from __future__ import annotations


def test_engine_status_endpoint(client):
    response = client.get("/api/v1/engine/status")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body


def test_engine_run_endpoint(client):
    response = client.post("/api/v1/engine/run", json={})
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["skill_count"] == 38
    assert body["avg_score"] >= 0


def test_engine_run_endpoint_with_selected_skills(client):
    response = client.post(
        "/api/v1/engine/run",
        json={"selected_skills": ["market-news-analyst", "us-stock-analysis"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["selected_count"] == 2


def test_skills_catalog_endpoint(client):
    response = client.get("/api/v1/skills")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 38
    assert isinstance(body["skills"], list)
    assert body["skills"][0]["slug"]
