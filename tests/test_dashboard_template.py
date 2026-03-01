from __future__ import annotations


def test_healthz_endpoint_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_template_renders_required_sections(client):
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text
    assert "스킬 선택" in html
    assert "선택한 스킬 실행" in html
    assert "종목추천 스킬" in html
    assert "분석 스킬" in html
    assert "티커 필터 (선택)" in html
    assert "개별 티커" in html
    assert "멀티 티커" in html
    assert "스킬 실행 결과" in html
    assert "추천 종목 (선택 스킬 기반)" in html
    assert "요약 TOP5" in html
    assert "최종 교집합 TOP5" in html
    assert "선택 스킬 점수 TOP5" in html
    assert "추천 스킬별 결과 테이블" in html
    assert "추천 교집합 테이블" in html
    assert "추천 합집합 정규화 TOP10 테이블" in html
    assert "분석 스킬별 평가 테이블 (타겟 분리)" in html
    assert "최종 결과 요약 (교집합 + TOP5)" in html
    assert "AI 최종 리포트 생성" in html
    assert "AI 최종 리포트 (GLM 4.5)" in html
    assert "데이터 소스" in html
    assert "투자 권유 아님" in html
    assert "무효화 레벨 확인" in html
    assert "추천 생성 방식" not in html
    assert "watchlist (콤마/공백 구분)" not in html
    assert "primary_skill (추천 1개)" not in html
    assert "two-stage recommender skills (콤마, 최대 5)" not in html


def test_dashboard_template_uses_ko_date_display(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "2026. 02. 26." in response.text


def test_dashboard_template_includes_seo_and_pwa_meta(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert 'name="description"' in html
    assert 'rel="canonical"' in html
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'property="og:title"' in html


def test_dashboard_template_profile_switch(client):
    response = client.get("/dashboard", params={"profile": "aggressive"})
    assert response.status_code == 200
    assert "스킬 선택" in response.text


def test_dashboard_template_renders_korean_ticker_alias(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "S&amp;P500 ETF" in response.text


def test_web_basics_endpoints_render(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap: /sitemap.xml" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text
    assert "/dashboard" in sitemap.text

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/dashboard"

    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "serviceWorker" not in sw.text
    assert "CACHE_NAME" in sw.text


def test_ai_report_run_get_redirects_to_dashboard(client):
    response = client.get("/dashboard/ai-report/run", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
