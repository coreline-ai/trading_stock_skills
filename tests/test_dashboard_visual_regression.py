from __future__ import annotations

from bs4 import BeautifulSoup


def test_mobile_layout_structure_regression(client):
    response = client.get("/dashboard")
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")

    viewport = soup.find("meta", attrs={"name": "viewport"})
    assert viewport is not None
    assert viewport.get("content") == "width=device-width, initial-scale=1.0"

    sections = soup.find_all("section")
    assert len(sections) >= 2

    titles = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    assert any("스킬 선택" in title for title in titles)
    assert any("스킬 실행 결과" in title for title in titles)
    assert any("추천 종목" in title for title in titles)
    assert any("요약 TOP5" in title for title in titles)
    assert any("추천 스킬별 결과 테이블" in title for title in titles)
    assert any("추천 교집합 테이블" in title for title in titles)
    assert any("추천 합집합 정규화 TOP10 테이블" in title for title in titles)
    assert any("분석 스킬별 평가 테이블 (타겟 분리)" in title for title in titles)
    assert any("최종 결과 요약 (교집합 + TOP5)" in title for title in titles)
    assert "종목추천 스킬" in soup.get_text(" ")
    assert "분석 스킬" in soup.get_text(" ")

    cards = soup.find_all("article")
    assert len(cards) >= 1


def test_guardrail_badges_always_visible(client):
    response = client.get("/dashboard")
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ")
    assert "투자 권유 아님" in text
    assert "무효화 레벨 확인" in text
