from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trading_skills_engine.web.app import create_app


@pytest.fixture(autouse=True)
def isolate_market_scope_runtime(tmp_path: Path, monkeypatch):
    scope_path = tmp_path / "market_scope.json"
    scope_path.write_text(json.dumps({"scope": "US"}), encoding="utf-8")
    monkeypatch.setenv("MARKET_SCOPE", "US")
    monkeypatch.setenv("MARKET_SCOPE_RUNTIME_SETTINGS_PATH", str(scope_path))


@pytest.fixture(autouse=True)
def seed_us_universe_cache_for_app_tests(tmp_path: Path, monkeypatch, request):
    # Keep provider unit tests in full control of cache_path inputs.
    if str(request.node.fspath).endswith("test_market_data_provider.py"):
        return

    cache_path = tmp_path / "cache" / "us_universe.json"
    symbols_list = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "LLY", "JPM",
        "V", "XOM", "UNH", "WMT", "MA", "COST", "ORCL", "HD", "PG", "NFLX",
        "BAC", "ABBV", "KO", "CRM", "AMD", "PEP", "MRK", "ADBE", "LIN", "CSCO",
        "INTU", "QCOM", "IBM", "MCD", "GE", "TXN", "AMAT", "NOW", "CAT", "PFE",
    ]
    sectors = ["Technology", "Health Care", "Financials", "Consumer", "Energy", "Industrials"]
    rows = []
    size = len(symbols_list)
    for idx, symbol in enumerate(symbols_list):
        ai_factor = 0.95 - (idx / max(1, size - 1)) * 0.6
        rows.append(
            {
                "symbol": symbol,
                "name": symbol,
                "sector": sectors[idx % len(sectors)],
                "daily_return_pct": round(((idx % 11) - 5) * 0.6, 3),
                "momentum_20d": round(((idx % 13) - 6) * 1.4, 3),
                "ai_factor": round(max(0.35, min(0.95, ai_factor)), 4),
            }
        )
    payload = {
        "scope": "US",
        "source": "live",
        "source_provider": "fmp",
        "universe_mode": "SP500_PLUS_NASDAQ_TOP500",
        "ranking_basis": "market_cap",
        "raw_count": len(rows),
        "filtered_count": len(rows),
        "selected_count": len(rows),
        "sp500_count": 25,
        "nasdaq_top500_count": 25,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "symbols": rows,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("US_UNIVERSE_CACHE_PATH", str(cache_path))


@pytest.fixture()
def sample_snapshot_path(tmp_path: Path) -> Path:
    payload = {
        "app_name": "Coreline Stock AI",
        "as_of_date": "2026-02-26",
        "notification_count": 3,
        "data_source": "unavailable",
        "selected_skills": ["market-news-analyst", "us-stock-analysis"],
        "user_avatar_url": "https://example.com/avatar.png",
        "auto_rebalance_enabled": True,
        "strategy_profiles": {
            "balanced": {"profitability": 0.36, "stability": 0.32, "growth": 0.32},
            "aggressive": {"profitability": 0.25, "stability": 0.15, "growth": 0.60},
            "defensive": {"profitability": 0.30, "stability": 0.55, "growth": 0.15},
        },
        "skill_classification_counts": {"decline": 13, "neutral": 1, "growth": 32},
        "top_picks": [
            {
                "symbol": "AAPL",
                "name": "Apple",
                "sector": "Tech",
                "return_pct": 3.4,
                "ai_score_10": 8.1,
                "sparkline_points": [30, 34, 33, 37, 45, 50, 54],
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft",
                "sector": "Tech",
                "return_pct": 2.8,
                "ai_score_10": 7.9,
                "sparkline_points": [33, 35, 36, 38, 40, 44, 48],
            },
        ],
        "skill_runs": [
            {
                "skill_slug": "market-news-analyst",
                "status": "growth",
                "score_0_100": 71.3,
                "confidence_0_1": 0.81,
                "narrative_ko": "뉴스 임팩트가 성장 우위로 나타났습니다.",
            },
            {
                "skill_slug": "us-stock-analysis",
                "status": "neutral",
                "score_0_100": 56.2,
                "confidence_0_1": 0.64,
                "narrative_ko": "밸류에이션은 중립, 모멘텀은 양호합니다.",
            },
        ],
        "quality_summary": {"avg_score": 63.75, "low_score_skills": []},
    }

    path = tmp_path / "latest_snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def sample_v2_report_path(tmp_path: Path) -> Path:
    payload = {
        "run_id": "test-run-id",
        "as_of_date": "2026-02-26",
        "data_sources": {"fmp": "stale", "rss": "live"},
        "results": [
            {
                "skill_slug": "market-news-analyst",
                "status": "ok",
                "score_0_100": 67.2,
                "confidence_0_1": 0.7,
                "summary_ko": "RSS 기반 뉴스 랭킹을 생성했습니다.",
                "reason_code": None,
                "cache_info": {"mode": "fresh", "fetched_at": None, "expires_at": None},
                "analysis_payload": {
                    "ranked_events": [
                        {
                            "headline": "Fed signals cautious stance",
                            "published_at": "2026-02-26T00:00:00+00:00",
                            "source": "Federal Reserve",
                            "price_impact": 1.2,
                            "breadth": 1.3,
                            "forward_significance": 1.1,
                            "impact_score": 1.72,
                            "source_url": "https://example.com",
                            "related_tickers": ["SPY"],
                        }
                    ],
                    "theme_clusters": {"macro": 1},
                },
                "source_statuses": {"fmp": "stale", "rss": "live"},
            }
        ],
        "top_picks": [{"symbol": "SPY", "reason": "v2 skill consensus", "score": 12.3}],
        "warnings": [],
    }

    path = tmp_path / "latest_skill_runs_v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def app(sample_snapshot_path: Path, sample_v2_report_path: Path, monkeypatch):
    monkeypatch.setenv("SKILL_RUN_REPORT_V2_PATH", str(sample_v2_report_path))
    return create_app(snapshot_path=sample_snapshot_path)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)
