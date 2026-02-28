from __future__ import annotations

import json
from datetime import date
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


def test_v2_skills_catalog_has_expanded_implemented_set(client):
    response = client.get("/api/v2/skills")
    assert response.status_code == 200
    body = response.json()

    by_slug = {item["slug"]: item for item in body}
    for slug in {
        "market-breadth-analyzer",
        "uptrend-analyzer",
        "market-top-detector",
        "ftd-detector",
        "earnings-trade-analyzer",
        "portfolio-manager",
    }:
        assert by_slug[slug]["implemented"] is True
    assert sum(1 for item in body if item["implemented"]) == 38


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
    assert set(body.keys()) == {"run_id", "as_of_date", "data_sources", "results", "top_picks", "pipeline", "warnings"}
    assert body["as_of_date"] == "2026-02-26"
    assert set(body["data_sources"].keys()) == {"fmp", "rss"}
    assert len(body["results"]) == 4
    assert body["pipeline"] is None

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


def test_v2_market_news_runs_with_rss_without_fmp_key(client, monkeypatch):
    from trading_skills_engine.data.rss_client import RSSClient

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    def _fake_fetch(self, max_items=80):
        del max_items
        return (
            [
                {
                    "headline": "Fed signals cautious rate stance",
                    "source": "Federal Reserve",
                    "source_url": "https://example.com/fed",
                    "published_at": "2026-02-26T10:00:00+00:00",
                }
            ],
            [],
        )

    monkeypatch.setattr(RSSClient, "fetch", _fake_fetch)

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": ["market-news-analyst"],
            "as_of_date": "2037-01-15",
            "params_by_skill": {"market-news-analyst": {"lookback_days": 37, "max_items": 17}},
        },
    )
    assert response.status_code == 200

    result = response.json()["results"][0]
    assert result["status"] == "ok"
    assert result["source_statuses"]["fmp"] == "unavailable"
    assert result["source_statuses"]["rss"] == "live"


def test_market_news_extract_tickers_filters_noise_tokens():
    from trading_skills_engine.skills_v2.market_news import _extract_tickers

    tickers = _extract_tickers("NYSE and FOMC updates mention NVDA and TSLA with USD strength")
    assert "NVDA" in tickers
    assert "TSLA" in tickers
    assert "NYSE" not in tickers
    assert "FOMC" not in tickers
    assert "USD" not in tickers


def test_v2_watchlist_consensus_mode_filters_to_watchlist(client, monkeypatch):
    from trading_skills_engine.data.rss_client import RSSClient

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    def _fake_fetch(self, max_items=80):
        del max_items
        return (
            [
                {
                    "headline": "FOMC signals cautious stance for rates",
                    "source": "Federal Reserve",
                    "source_url": "https://example.com/fomc",
                    "published_at": "2026-02-26T10:00:00+00:00",
                }
            ],
            [],
        )

    monkeypatch.setattr(RSSClient, "fetch", _fake_fetch)

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": ["market-news-analyst", "us-stock-analysis"],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "watchlist_consensus",
            "watchlist_symbols": ["NVDA", "AAPL"],
            "top_picks_limit": 1,
            "params_by_skill": {"us-stock-analysis": {"ticker": "NVDA"}},
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["top_picks"]) == 1
    assert all(item["symbol"] in {"NVDA", "AAPL"} for item in body["top_picks"])
    assert all(item["reason"] == "watchlist consensus" for item in body["top_picks"])


def test_v2_role_gated_consensus_returns_decision_reason(client, monkeypatch):
    from trading_skills_engine.data.rss_client import RSSClient

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    def _fake_fetch(self, max_items=80):
        del max_items
        return (
            [
                {
                    "headline": "NVDA momentum extends after earnings",
                    "source": "Example Desk",
                    "source_url": "https://example.com/nvda",
                    "published_at": "2026-02-26T10:00:00+00:00",
                }
            ],
            [],
        )

    monkeypatch.setattr(RSSClient, "fetch", _fake_fetch)

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "uptrend-analyzer",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "role_gated_consensus",
            "watchlist_symbols": ["NVDA", "AAPL", "MSFT"],
            "top_picks_limit": 2,
            "params_by_skill": {
                "us-stock-analysis": {"ticker": "NVDA"},
                "top-picks": {
                    "primary_skill": "us-stock-analysis",
                    "confirm_skills": "market-news-analyst,uptrend-analyzer",
                    "analysis_skills": "macro-regime-detector",
                    "min_confirm_votes": 1,
                },
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["top_picks"]) == 2
    assert all("role gated" in item["reason"] for item in body["top_picks"])
    assert any(any(tag in item["reason"] for tag in ["PASS", "WATCH", "REJECT"]) for item in body["top_picks"])
    assert all(item.get("decision") in {"PASS", "WATCH", "REJECT"} for item in body["top_picks"])
    assert all(item.get("primary_skill") for item in body["top_picks"])


def test_v2_two_stage_all_pass_fallback_to_watch_on_empty(client, monkeypatch):
    from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
    from trading_skills_engine.skills_v2.contracts import AnalyzerEvaluationV2

    def _always_watch(
        symbol,
        result,
        source_recommender=None,
        target_group=None,
    ):
        del result
        return AnalyzerEvaluationV2(
            symbol=str(symbol),
            source_recommender=source_recommender,
            target_group=target_group if target_group in {"intersection", "top10"} else None,
            decision="WATCH",
            score=60.0,
            reasons=["test watch decision"],
            risk_flags=[],
        )

    monkeypatch.setattr(
        SkillEngineOrchestratorV2,
        "_evaluate_symbol_for_analyzer",
        staticmethod(_always_watch),
    )

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "vcp-screener",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
                "recommender_skills": ["vcp-screener"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 10,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "all_pass",
            },
            "params_by_skill": {
                "top-picks": {
                    "fallback_to_watch_on_empty": True,
                }
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    pipeline = body["pipeline"]

    assert pipeline["final_summary"]["policy_used"] == "pass_or_watch"
    assert pipeline["final_summary"]["top5_from_top10"]
    assert "analyzer_filtered_top10_empty[all_pass]" in pipeline["final_summary"]["dropped_by_stage"]
    assert "fallback_pass_or_watch_applied" in pipeline["final_summary"]["dropped_by_stage"]


def test_v2_two_stage_intersection_contract(client, monkeypatch):
    from trading_skills_engine.data.rss_client import RSSClient

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    monkeypatch.setattr(
        RSSClient,
        "fetch",
        lambda self, max_items=80: (
            [
                {
                    "headline": "NVDA and MSFT lead AI momentum",
                    "source": "Example Desk",
                    "source_url": "https://example.com/ai",
                    "published_at": "2026-02-26T10:00:00+00:00",
                }
            ],
            [],
        ),
    )

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "uptrend-analyzer",
                "macro-regime-detector",
                "market-environment-analysis",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "watchlist_symbols": ["NVDA", "MSFT", "AAPL"],
            "top_picks_limit": 3,
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis", "market-news-analyst"],
                "analyzer_skills": ["macro-regime-detector", "market-environment-analysis"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "all_pass",
            },
            "params_by_skill": {"us-stock-analysis": {"ticker": "NVDA"}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline"] is not None
    pipeline = body["pipeline"]
    assert {
        "recommender_outputs",
        "recommender_intersection",
        "recommender_union_top10",
        "analysis_targets",
        "analyzer_outputs",
        "analyzer_outputs_by_target",
        "final_intersection",
        "final_summary",
    }.issubset(set(pipeline.keys()))
    assert len(pipeline["recommender_outputs"]) >= 1
    assert "symbols" in pipeline["recommender_intersection"]
    assert "final_reasons" in pipeline["final_intersection"]
    assert "post_analyzer_by_recommender" in pipeline["final_intersection"]
    assert "symbols" in pipeline["recommender_union_top10"]
    assert len(pipeline["recommender_union_top10"]["symbols"]) <= 10
    assert "top10_symbols" in pipeline["analysis_targets"]
    if pipeline["analyzer_outputs_by_target"]:
        first_eval = pipeline["analyzer_outputs_by_target"][0]["evaluations"][0] if pipeline["analyzer_outputs_by_target"][0]["evaluations"] else {}
        if first_eval:
            assert first_eval.get("target_group") in {"intersection", "top10"}
    assert "top5_from_top10" in pipeline["final_summary"]
    assert all("two-stage top10 analysis" in item["reason"] for item in body["top_picks"])


def test_v2_two_stage_trim_limits_and_warnings(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "uptrend-analyzer",
                "market-breadth-analyzer",
                "vcp-screener",
                "canslim-screener",
                "macro-regime-detector",
                "market-environment-analysis",
                "scenario-analyzer",
                "edge-candidate-agent",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
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
                "recommender_top_n": 20,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "all_pass",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    pipeline = body["pipeline"]
    assert pipeline is not None
    assert len(pipeline["recommender_outputs"]) <= 5
    assert len(pipeline["analyzer_outputs"]) <= 3
    warning_text = " ".join(body["warnings"])
    assert "최대 5개" in warning_text
    assert "최대 3개" in warning_text


def test_v2_two_stage_watch_policy_comparison_mode(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "pass_or_watch",
                "comparison_mode": True,
            },
            "params_by_skill": {
                "us-stock-analysis": {"ticker": "NVDA"},
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    pipeline = body["pipeline"]
    assert pipeline is not None
    final_intersection = pipeline["final_intersection"]
    assert final_intersection["policy_used"] == "pass_or_watch"
    assert final_intersection["comparison"].get("enabled") is True
    strict_count = final_intersection["comparison"]["strict_all_pass"]["count"]
    watch_count = final_intersection["comparison"]["watch_inclusive"]["count"]
    assert watch_count >= strict_count
    assert all("analyzer pass-or-watch" in item["reason"] for item in body["top_picks"])


def test_v2_two_stage_single_recommender_has_empty_intersection(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "pass_or_watch",
            },
            "params_by_skill": {
                "us-stock-analysis": {"ticker": "NVDA"},
            },
        },
    )
    assert response.status_code == 200
    pipeline = response.json()["pipeline"]
    assert pipeline is not None
    assert pipeline["recommender_intersection"]["symbols"] == []
    assert pipeline["analysis_targets"]["intersection_symbols"] == []


def test_v2_two_stage_strict_empty_intersection_keeps_empty_results(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis", "market-news-analyst"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "all_pass",
            },
            "watchlist_symbols": ["ZZZZ"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["top_picks"] == []
    pipeline = body["pipeline"]
    assert pipeline is not None
    assert pipeline["recommender_intersection"]["symbols"] == []
    assert pipeline["analysis_targets"]["intersection_symbols"] == []


def test_v2_two_stage_analysis_runs_for_intersection_and_top10_targets(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis", "market-news-analyst"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "pass_or_watch",
            },
            "params_by_skill": {"us-stock-analysis": {"ticker": "NVDA"}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    pipeline = body["pipeline"]
    assert pipeline is not None
    target_outputs = pipeline["analyzer_outputs_by_target"]
    target_groups = {row["target_group"] for row in target_outputs}
    assert {"intersection", "top10"}.issubset(target_groups)
    assert len(pipeline["recommender_union_top10"]["symbols"]) <= 10
    assert len(pipeline["final_summary"]["top5_from_top10"]) <= 5


def test_v2_two_stage_empty_top10_records_drop_stage(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "us-stock-analysis",
                "market-news-analyst",
                "macro-regime-detector",
            ],
            "as_of_date": "2026-02-26",
            "top_picks_mode": "two_stage_intersection",
            "watchlist_symbols": ["ZZZZ"],
            "pipeline_config": {
                "recommender_skills": ["us-stock-analysis", "market-news-analyst"],
                "analyzer_skills": ["macro-regime-detector"],
                "recommender_top_n": 25,
                "intersection_policy": "strict",
                "analyzer_pass_policy": "all_pass",
            },
        },
    )
    assert response.status_code == 200
    pipeline = response.json()["pipeline"]
    assert pipeline is not None
    assert pipeline["recommender_union_top10"]["symbols"] == []
    assert "recommender_union_top10_empty" in pipeline["final_summary"]["dropped_by_stage"]


def test_v2_new_analyzers_run_without_fmp_key(client, monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    selected = [
        "market-breadth-analyzer",
        "uptrend-analyzer",
        "market-top-detector",
        "ftd-detector",
        "earnings-trade-analyzer",
        "portfolio-manager",
    ]
    response = client.post(
        "/api/v2/skills/run",
        json={"selected_skills": selected, "as_of_date": "2026-02-26"},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == len(selected)
    assert all(item["status"] == "ok" for item in results)


def test_v2_core_skills_degrade_ok_without_fmp_key(client, monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": [
                "economic-calendar-fetcher",
                "earnings-calendar",
                "us-stock-analysis",
            ],
            "as_of_date": "2042-01-13",
            "params_by_skill": {
                "economic-calendar-fetcher": {"from_days": 11, "to_days": 37, "country": "US"},
                "earnings-calendar": {"days": 13, "min_market_cap": 123456789},
                "us-stock-analysis": {"ticker": "ZZZZ"},
            },
        },
    )
    assert response.status_code == 200

    by_slug = {item["skill_slug"]: item for item in response.json()["results"]}
    for slug in ["economic-calendar-fetcher", "earnings-calendar", "us-stock-analysis"]:
        assert by_slug[slug]["status"] == "ok"
        assert by_slug[slug]["source_statuses"]["fmp"] in {"stale", "unavailable"}


def test_v2_core_skills_fallback_to_proxy_when_fmp_fetch_fails(tmp_path: Path, monkeypatch):
    from trading_skills_engine.data.cache_store import CacheStore as RealCacheStore
    from trading_skills_engine.data.rss_client import RSSClient
    import trading_skills_engine.engine.orchestrator_v2 as orchestrator_v2_mod

    class _FailingCalendar:
        def get_economic_calendar(self, start, end, country="US"):
            del start, end, country
            raise RuntimeError("forced-calendar-failure")

        def get_earnings_calendar(self, start, end):
            del start, end
            raise RuntimeError("forced-calendar-failure")

    class _FailingNews:
        def get_quote(self, symbol):
            del symbol
            raise RuntimeError("forced-news-failure")

        def get_profile(self, symbol):
            del symbol
            raise RuntimeError("forced-news-failure")

        def get_key_metrics_ttm(self, symbol):
            del symbol
            raise RuntimeError("forced-news-failure")

        def get_peers(self, symbol):
            del symbol
            raise RuntimeError("forced-news-failure")

    monkeypatch.setenv("FMP_API_KEY", "dummy-key")
    monkeypatch.setattr(orchestrator_v2_mod, "CacheStore", lambda _path: RealCacheStore(tmp_path / "cache_v2"))
    monkeypatch.setattr(
        orchestrator_v2_mod.FMPCalendarClient,
        "from_env",
        classmethod(lambda cls: _FailingCalendar()),
    )
    monkeypatch.setattr(
        orchestrator_v2_mod.FMPNewsClient,
        "from_env",
        classmethod(lambda cls: _FailingNews()),
    )
    monkeypatch.setattr(
        RSSClient,
        "fetch",
        lambda self, max_items=80: (
            [
                {
                    "headline": "US CPI preview: inflation to cool",
                    "source": "Example Macro Desk",
                    "source_url": "https://example.com/cpi",
                    "published_at": "2026-02-26T10:00:00+00:00",
                }
            ],
            [],
        ),
    )

    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))
    app = create_app()
    with TestClient(app) as isolated_client:
        response = isolated_client.post(
            "/api/v2/skills/run",
            json={
                "selected_skills": [
                    "economic-calendar-fetcher",
                    "earnings-calendar",
                    "us-stock-analysis",
                ],
                "as_of_date": "2026-02-26",
                "params_by_skill": {
                    "us-stock-analysis": {"ticker": "AAPL"},
                },
            },
        )

    assert response.status_code == 200
    by_slug = {item["skill_slug"]: item for item in response.json()["results"]}

    assert by_slug["economic-calendar-fetcher"]["status"] == "ok"
    assert by_slug["economic-calendar-fetcher"]["source_statuses"]["fmp"] == "unavailable"
    assert by_slug["economic-calendar-fetcher"]["analysis_payload"]["mode"] == "rss_proxy"

    assert by_slug["earnings-calendar"]["status"] == "ok"
    assert by_slug["earnings-calendar"]["source_statuses"]["fmp"] == "unavailable"
    assert by_slug["earnings-calendar"]["analysis_payload"]["mode"] == "market_state_proxy"

    assert by_slug["us-stock-analysis"]["status"] == "ok"
    assert by_slug["us-stock-analysis"]["source_statuses"]["fmp"] == "unavailable"
    assert by_slug["us-stock-analysis"]["analysis_payload"]["mode"] == "market_state_proxy"


def test_v2_invalid_slug_returns_unavailable(client):
    response = client.post(
        "/api/v2/skills/run",
        json={"selected_skills": ["unknown-skill-xyz"], "as_of_date": "2026-02-26"},
    )
    assert response.status_code == 200

    result = response.json()["results"][0]
    assert result["skill_slug"] == "unknown-skill-xyz"
    assert result["status"] == "unavailable"
    assert result["reason_code"] == "INVALID_SKILL"
    assert result["score_0_100"] is None
    assert result["confidence_0_1"] is None


def test_v2_run_sanitizes_duplicate_and_invalid_selected_skills(client):
    response = client.post(
        "/api/v2/skills/run",
        json={
            "selected_skills": ["vcp-screener", "vcp-screener", "   ", "x" * 120],
            "as_of_date": "2026-02-26",
        },
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["skill_slug"] == "vcp-screener"


def test_dashboard_run_renders_proxy_result(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        run_response = isolated_client.post(
            "/dashboard/run",
            data={"recommender_skills": ["vcp-screener"]},
            follow_redirects=False,
        )
        assert run_response.status_code == 303
        assert run_response.headers["location"] == "/dashboard"

        page = isolated_client.get("/dashboard")
        assert page.status_code == 200
        assert "vcp-screener" in page.text
        assert "ok" in page.text


def test_dashboard_run_filters_invalid_and_duplicate_slugs(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        run_response = isolated_client.post(
            "/dashboard/run",
            data={
                "recommender_skills": ["vcp-screener", "invalid-slug", "vcp-screener"],
                "analyzer_skills": ["macro-regime-detector", "invalid-slug", "macro-regime-detector"],
            },
            follow_redirects=False,
        )
        assert run_response.status_code == 303

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    slugs = [item.get("skill_slug") for item in results if isinstance(item, dict)]
    assert slugs == ["vcp-screener", "macro-regime-detector"]


def test_dashboard_run_rejects_oversized_form_body(client):
    oversized = "skills=" + ("x" * 70_000)
    response = client.post(
        "/dashboard/run",
        content=oversized,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_dashboard_fmp_toggle_and_usage_display(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "latest_skill_runs_v2.json"
    report_payload = {
        "run_id": "toggle-test",
        "as_of_date": "2026-02-26",
        "data_sources": {"fmp": "stale", "rss": "live"},
        "results": [],
        "top_picks": [],
        "warnings": [],
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    settings_path = tmp_path / "runtime" / "fmp_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"enabled": True, "daily_limit": 250}), encoding="utf-8")

    usage_path = tmp_path / "runtime" / "fmp_usage.json"
    usage_path.write_text(
        json.dumps({"date": date.today().isoformat(), "used_today": 121}),
        encoding="utf-8",
    )

    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(report_path))
    monkeypatch.setenv("FMP_RUNTIME_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("FMP_USAGE_PATH", str(usage_path))

    app = create_app()
    with TestClient(app) as isolated_client:
        page = isolated_client.get("/dashboard")
        assert page.status_code == 200
        assert "FMP ON" in page.text
        assert "사용량 121/250" in page.text

        toggle_response = isolated_client.post(
            "/dashboard/fmp-toggle",
            data={"enabled": "0"},
            follow_redirects=False,
        )
        assert toggle_response.status_code == 303
        assert toggle_response.headers["location"] == "/dashboard"

        stored = json.loads(settings_path.read_text(encoding="utf-8"))
        assert stored["enabled"] is False

        page_after = isolated_client.get("/dashboard")
        assert page_after.status_code == 200
        assert "FMP OFF" in page_after.text
        assert "사용량 121/250" in page_after.text

        status = isolated_client.get("/api/v2/engine/status")
        assert status.status_code == 200
        runtime = status.json()["fmp_runtime"]
        assert runtime["toggle_enabled"] is False
        assert runtime["usage_label"] == "121/250"
