from __future__ import annotations


def test_header_contract(client):
    response = client.get("/api/v1/dashboard/header")
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {"app_name", "as_of_date", "notification_count", "user_avatar_url"}
    assert isinstance(body["app_name"], str)
    assert isinstance(body["as_of_date"], str)
    assert isinstance(body["notification_count"], int)
    assert isinstance(body["user_avatar_url"], str)


def test_strategy_weighting_contract(client):
    response = client.get("/api/v1/dashboard/strategy-weighting", params={"profile": "defensive"})
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {
        "profile",
        "profitability",
        "stability",
        "growth",
        "auto_rebalance_enabled",
    }
    assert body["profile"] == "defensive"
    assert 0 <= body["profitability"] <= 1
    assert 0 <= body["stability"] <= 1
    assert 0 <= body["growth"] <= 1
    assert isinstance(body["auto_rebalance_enabled"], bool)


def test_market_overview_contract(client):
    response = client.get("/api/v1/dashboard/market-overview")
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {"decline_count", "neutral_count", "growth_count"}
    assert isinstance(body["decline_count"], int)
    assert isinstance(body["neutral_count"], int)
    assert isinstance(body["growth_count"], int)


def test_top_picks_contract(client):
    response = client.get("/api/v1/dashboard/top-picks", params={"limit": 5})
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2

    first = body[0]
    assert set(first.keys()) == {
        "symbol",
        "name",
        "sector",
        "return_pct",
        "ai_score_10",
        "sparkline_points",
    }
    assert isinstance(first["symbol"], str)
    assert isinstance(first["name"], str)
    assert isinstance(first["sector"], str)
    assert isinstance(first["return_pct"], (float, int))
    assert isinstance(first["ai_score_10"], (float, int))
    assert isinstance(first["sparkline_points"], list)


def test_footer_nav_contract(client):
    response = client.get("/api/v1/dashboard/footer-nav")
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 4

    for item in body:
        assert set(item.keys()) == {"id", "label", "icon", "active"}
        assert isinstance(item["id"], str)
        assert isinstance(item["label"], str)
        assert isinstance(item["icon"], str)
        assert isinstance(item["active"], bool)


def test_dashboard_skills_contract(client):
    response = client.get("/api/v1/dashboard/skills")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert body
    first = body[0]
    assert set(first.keys()) == {"slug", "display_name", "family", "selected"}


def test_dashboard_skill_results_contract(client):
    response = client.get("/api/v1/dashboard/skill-results", params={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
