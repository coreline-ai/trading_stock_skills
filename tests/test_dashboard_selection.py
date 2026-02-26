from __future__ import annotations


def test_dashboard_run_post_redirects(client):
    response = client.post(
        "/dashboard/run",
        data={"skills": ["market-news-analyst", "us-stock-analysis"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
