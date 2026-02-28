from __future__ import annotations


def test_dashboard_template_renders_required_sections(client):
    response = client.get("/dashboard")
    assert response.status_code == 200

    html = response.text
    assert "스킬 선택" in html
    assert "선택한 스킬 실행" in html
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
    assert "WATCH 포함 교집합 사용" in html
    assert "비교 모드 (all_pass vs pass_or_watch)" in html
    assert "데이터 소스" in html
    assert "투자 권유 아님" in html
    assert "무효화 레벨 확인" in html


def test_dashboard_template_uses_ko_date_display(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "2026. 02. 26." in response.text


def test_dashboard_template_profile_switch(client):
    response = client.get("/dashboard", params={"profile": "aggressive"})
    assert response.status_code == 200
    assert "스킬 선택" in response.text
