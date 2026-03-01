from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_skills_engine.ai.report_service import AIReportService


def _write_source_report(path: Path, with_top5: bool = True) -> None:
    payload = {
        "run_id": "run-123",
        "as_of_date": "2026-02-28",
        "top_picks": [
            {"symbol": "NVDA", "score": 91.0, "reason": "fallback"},
            {"symbol": "AVGO", "score": 87.0, "reason": "fallback"},
        ],
    }
    if with_top5:
        payload["pipeline"] = {
            "final_summary": {
                "top5_from_top10": [
                    {"symbol": "NVDA", "final_score": 88.2, "support_count": 5, "analyzer_avg_score": 72.1},
                    {"symbol": "AVGO", "final_score": 84.5, "support_count": 4, "analyzer_avg_score": 69.2},
                ]
            }
        }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class _FakeGLMClient:
    model = "glm-4.5"

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:  # noqa: ARG002
        return {
            "portfolio_summary_ko": "포트폴리오 요약",
            "symbols": [
                {
                    "symbol": "NVDA",
                    "decision": "BUY",
                    "confidence_0_1": 0.81,
                    "score_0_100": 82.3,
                    "summary_ko": "상대 강세",
                    "reasons_ko": ["모멘텀 우위", "실적 기대"],
                    "risks_ko": ["변동성 확대"],
                },
                {
                    "symbol": "AVGO",
                    "decision": "WATCH",
                    "confidence_0_1": 0.62,
                    "score_0_100": 64.2,
                    "summary_ko": "관망 필요",
                    "reasons_ko": ["밸류 부담"],
                    "risks_ko": ["뉴스 변동성"],
                },
            ],
        }


def test_ai_report_service_generates_and_persists_with_fallback(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "latest_skill_runs_v2.json"
    ai_path = tmp_path / "latest_ai_report.json"
    _write_source_report(source_path, with_top5=True)

    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setattr("trading_skills_engine.ai.report_service.GLMClient.from_env", lambda: _FakeGLMClient())
    monkeypatch.setattr("trading_skills_engine.ai.report_service.FMPClient.from_env", lambda: None)
    monkeypatch.setattr(
        "trading_skills_engine.data.yahoo_finance_client.YahooFinanceClient.fetch_quote",
        lambda self, symbol: {  # noqa: ARG005
            "source": "yahoo",
            "url": f"https://finance.yahoo.com/quote/{symbol}",
            "metrics": {"price": 100.0},
        },
    )
    monkeypatch.setattr(
        "trading_skills_engine.data.stooq_client.StooqClient.fetch_quote",
        lambda self, symbol: {  # noqa: ARG005
            "source": "stooq",
            "url": f"https://stooq.com/{symbol}",
            "metrics": {"close": 99.0},
        },
    )

    service = AIReportService(source_report_path=source_path, ai_report_path=ai_path)

    report = service.generate_and_persist()
    assert report.status == "ok"
    assert report.model == "glm-4.5"
    assert len(report.symbols) == 2
    assert ai_path.exists()

    persisted = json.loads(ai_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "ok"
    assert persisted["symbols"][0]["symbol"] == "NVDA"
    assert persisted["symbols"][0]["evidence"]


def test_ai_report_service_returns_unavailable_when_key_missing(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "latest_skill_runs_v2.json"
    ai_path = tmp_path / "latest_ai_report.json"
    _write_source_report(source_path, with_top5=False)

    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    service = AIReportService(source_report_path=source_path, ai_report_path=ai_path)
    report = service.generate_and_persist()
    assert report.status == "unavailable"
    assert report.error_code == "GLM_API_KEY_MISSING"
    assert ai_path.exists()


def test_ai_report_service_read_runtime_marks_stale_running_as_failed(monkeypatch, tmp_path: Path):
    runtime_path = tmp_path / "runtime.json"
    ai_path = tmp_path / "latest_ai_report.json"
    started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": started,
                "updated_at": started,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("AI_REPORT_RUNNING_TTL_SEC", "600")

    service = AIReportService(ai_runtime_path=runtime_path, ai_report_path=ai_path)
    runtime = service.read_runtime()
    assert runtime["status"] == "failed"
    assert runtime["last_error_code"] == "AI_REPORT_RUNTIME_STALE"

    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert persisted["last_error_code"] == "AI_REPORT_RUNTIME_STALE"


def test_ai_report_service_read_runtime_recovers_running_when_new_report_exists(monkeypatch, tmp_path: Path):
    runtime_path = tmp_path / "runtime.json"
    ai_path = tmp_path / "latest_ai_report.json"
    started = datetime.now(timezone.utc) - timedelta(minutes=3)
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": started.isoformat(),
                "updated_at": started.isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    created_at = (started + timedelta(seconds=50)).isoformat()
    ai_path.write_text(
        json.dumps(
            {
                "run_id": "report-run-1",
                "created_at": created_at,
                "status": "ok",
                "error_code": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    service = AIReportService(ai_runtime_path=runtime_path, ai_report_path=ai_path)
    runtime = service.read_runtime()

    assert runtime["status"] == "idle"
    assert runtime["last_report_run_id"] == "report-run-1"
    assert runtime["last_report_status"] == "ok"
    assert runtime["finished_at"] == created_at


def test_ai_report_service_suppresses_yahoo_warning_when_stooq_fallback_succeeds(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "latest_skill_runs_v2.json"
    ai_path = tmp_path / "latest_ai_report.json"
    _write_source_report(source_path, with_top5=False)

    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setattr("trading_skills_engine.ai.report_service.GLMClient.from_env", lambda: _FakeGLMClient())
    monkeypatch.setattr("trading_skills_engine.ai.report_service.FMPClient.from_env", lambda: None)
    monkeypatch.setattr(
        "trading_skills_engine.data.yahoo_finance_client.YahooFinanceClient.fetch_quote",
        lambda self, symbol: (_ for _ in ()).throw(RuntimeError("YAHOO_HTTP_401")),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "trading_skills_engine.data.stooq_client.StooqClient.fetch_quote",
        lambda self, symbol: {  # noqa: ARG005
            "source": "stooq",
            "url": f"https://stooq.com/{symbol}",
            "metrics": {"close": 99.0},
        },
    )

    service = AIReportService(source_report_path=source_path, ai_report_path=ai_path)
    report = service.generate_and_persist()

    assert report.status == "ok"
    assert all(not str(item).startswith("YAHOO_FAIL:") for item in (report.warnings or []))
    assert all(any(ev.source == "stooq" for ev in row.evidence) for row in report.symbols)


def test_ai_report_service_read_runtime_respects_glm_worst_case_budget(monkeypatch, tmp_path: Path):
    runtime_path = tmp_path / "runtime.json"
    ai_path = tmp_path / "latest_ai_report.json"
    started = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": started,
                "updated_at": started,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("AI_REPORT_RUNNING_TTL_SEC", "600")
    monkeypatch.setenv("GLM_TIMEOUT_SEC", "180")
    monkeypatch.setenv("GLM_MAX_RETRIES", "4")

    service = AIReportService(ai_runtime_path=runtime_path, ai_report_path=ai_path)
    runtime = service.read_runtime()
    assert runtime["status"] == "running"


def test_ai_report_service_touch_runtime_updates_timestamp(monkeypatch, tmp_path: Path):
    runtime_path = tmp_path / "runtime.json"
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    runtime_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": old,
                "updated_at": old,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    service = AIReportService(ai_runtime_path=runtime_path)
    service._touch_runtime_if_running()

    refreshed = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert refreshed["status"] == "running"
    assert refreshed["updated_at"] != old
