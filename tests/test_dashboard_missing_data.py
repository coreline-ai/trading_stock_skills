from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from trading_skills_engine.web.app import create_app


def _build_client(snapshot_payload: dict, tmp_path: Path) -> TestClient:
    snapshot_path = tmp_path / "latest_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_payload), encoding="utf-8")
    app = create_app(snapshot_path=snapshot_path)
    return TestClient(app)


def test_missing_date_falls_back_to_today(tmp_path: Path):
    client = _build_client(
        {
            "app_name": "Coreline",
            "notification_count": 0,
            "top_picks": [],
            "skill_classification_counts": {},
        },
        tmp_path,
    )

    response = client.get("/api/v1/dashboard/header")
    assert response.status_code == 200
    assert response.json()["as_of_date"]


def test_missing_sparkline_uses_fallback(tmp_path: Path):
    client = _build_client(
        {
            "as_of_date": "2026-02-26",
            "top_picks": [
                {
                    "symbol": "TSLA",
                    "name": "Tesla",
                    "sector": "Auto",
                    "return_pct": 1.0,
                    "ai_score_10": 5.0,
                }
            ],
        },
        tmp_path,
    )

    response = client.get("/api/v1/dashboard/top-picks")
    assert response.status_code == 200
    points = response.json()[0]["sparkline_points"]
    assert isinstance(points, list)
    assert len(points) >= 2


def test_top_pick_shortage_is_handled(tmp_path: Path):
    client = _build_client(
        {
            "as_of_date": "2026-02-26",
            "top_picks": [
                {
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "sector": "Semicon",
                    "return_pct": 2.0,
                    "ai_score_10": 9.1,
                    "sparkline_points": [30, 40],
                }
            ],
        },
        tmp_path,
    )

    response = client.get("/api/v1/dashboard/top-picks", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body
    assert body[0]["symbol"] == "NVDA"


def test_dashboard_reads_live_snapshot_not_mock(tmp_path: Path):
    snapshot_path = tmp_path / "latest_snapshot.json"
    payload = {
        "as_of_date": "2026-02-26",
        "top_picks": [
            {
                "symbol": "AAA",
                "name": "Alpha",
                "sector": "Test",
                "return_pct": 1.0,
                "ai_score_10": 6.0,
                "sparkline_points": [20, 30, 40],
            }
        ],
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    app = create_app(snapshot_path=snapshot_path)
    client = TestClient(app)

    first_response = client.get("/api/v1/dashboard/top-picks")
    assert first_response.status_code == 200
    assert first_response.json()[0]["symbol"] == "AAA"

    payload["top_picks"][0]["symbol"] = "BBB"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    second_response = client.get("/api/v1/dashboard/top-picks")
    assert second_response.status_code == 200
    assert second_response.json()[0]["symbol"] == "BBB"
