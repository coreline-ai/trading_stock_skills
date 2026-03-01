from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_skills_engine.ai.contracts import AIReport, AISymbolDecision, EvidenceItem
from trading_skills_engine.ai.glm_client import GLMClient, GLMClientError
from trading_skills_engine.ai.zai_search_mcp_client import ZAISearchMCPClient
from trading_skills_engine.config.env import ensure_project_env_loaded
from trading_skills_engine.core.history_retention import prune_history_files
from trading_skills_engine.data.fmp_client import FMPClient
from trading_skills_engine.data.stooq_client import StooqClient
from trading_skills_engine.data.yahoo_finance_client import YahooFinanceClient

DEFAULT_V2_REPORT_PATH = Path("reports/skill_runs/latest_skill_runs_v2.json")
DEFAULT_AI_REPORT_PATH = Path("reports/ai/latest_ai_report.json")
DEFAULT_AI_RUNTIME_PATH = Path("reports/ai/runtime.json")
DEFAULT_AI_RUNNING_TTL_SEC = 600

logger = logging.getLogger(__name__)


class AIReportService:
    def __init__(
        self,
        source_report_path: Path | None = None,
        ai_report_path: Path | None = None,
        ai_runtime_path: Path | None = None,
    ) -> None:
        ensure_project_env_loaded()
        env_source_path = str(os.getenv("SKILL_RUN_REPORT_V2_PATH") or "").strip()
        env_ai_path = str(os.getenv("AI_REPORT_PATH") or "").strip()
        env_runtime_path = str(os.getenv("AI_REPORT_RUNTIME_PATH") or "").strip()
        env_runtime_ttl = str(os.getenv("AI_REPORT_RUNNING_TTL_SEC") or str(DEFAULT_AI_RUNNING_TTL_SEC)).strip()
        self.source_report_path = Path(env_source_path) if env_source_path else (source_report_path or DEFAULT_V2_REPORT_PATH)
        self.ai_report_path = Path(env_ai_path) if env_ai_path else (ai_report_path or DEFAULT_AI_REPORT_PATH)
        self.ai_runtime_path = Path(env_runtime_path) if env_runtime_path else (ai_runtime_path or DEFAULT_AI_RUNTIME_PATH)
        self.ai_history_dir = self.ai_report_path.parent / "history"
        self.ai_history_max_files = _coerce_int_env(
            "AI_REPORT_HISTORY_MAX_FILES",
            default=500,
            min_value=0,
            max_value=20_000,
        )
        self.ai_history_max_days = _coerce_int_env(
            "AI_REPORT_HISTORY_MAX_DAYS",
            default=0,
            min_value=0,
            max_value=3650,
        )
        try:
            self.running_ttl_sec = max(300, min(7200, int(env_runtime_ttl)))
        except ValueError:
            self.running_ttl_sec = DEFAULT_AI_RUNNING_TTL_SEC

        self.yahoo_client = YahooFinanceClient()
        self.stooq_client = StooqClient()
        self.zai_search_client = ZAISearchMCPClient.from_env()

    def api_configured(self) -> bool:
        ensure_project_env_loaded()
        return bool(str(os.getenv("GLM_API_KEY") or "").strip())

    def read_latest(self) -> dict[str, Any] | None:
        if not self.ai_report_path.exists():
            return None
        try:
            payload = json.loads(self.ai_report_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("failed to read ai report path=%s", self.ai_report_path, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def read_runtime(self) -> dict[str, Any]:
        if not self.ai_runtime_path.exists():
            return {"status": "idle"}
        try:
            payload = json.loads(self.ai_runtime_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("failed to read ai runtime path=%s", self.ai_runtime_path, exc_info=True)
            return {"status": "idle"}
        if not isinstance(payload, dict):
            return {"status": "idle"}
        payload.setdefault("status", "idle")
        if str(payload.get("status") or "").lower() == "running":
            if self._recover_runtime_from_latest_report(payload):
                return payload
            if self._is_runtime_stale(payload):
                finished_at = _now_iso()
                payload["status"] = "failed"
                payload["finished_at"] = finished_at
                payload["updated_at"] = finished_at
                payload["last_error_code"] = "AI_REPORT_RUNTIME_STALE"
                self._write_runtime(payload)
        return payload

    def run_with_runtime(self) -> AIReport:
        started_at = _now_iso()
        self._write_runtime(
            {
                "status": "running",
                "started_at": started_at,
                "updated_at": started_at,
            }
        )
        try:
            report = self.generate_and_persist()
        except Exception as exc:
            logger.exception("ai report runtime execution failed")
            report = AIReport(
                status="unavailable",
                portfolio_summary_ko="AI 리포트 실행 중 내부 오류가 발생했습니다.",
                warnings=[f"AI_REPORT_INTERNAL_ERROR:{type(exc).__name__}"],
                error_code="AI_REPORT_INTERNAL_ERROR",
            )
            self._persist(report)
            finished_at = _now_iso()
            self._write_runtime(
                {
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    "last_report_run_id": report.run_id,
                    "last_report_status": report.status,
                    "last_error_code": report.error_code,
                }
            )
            return report

        finished_at = _now_iso()
        self._write_runtime(
            {
                "status": "idle",
                "started_at": started_at,
                "finished_at": finished_at,
                "updated_at": finished_at,
                "last_report_run_id": report.run_id,
                "last_report_status": report.status,
                "last_error_code": report.error_code,
            }
        )
        return report

    def generate_and_persist(self) -> AIReport:
        source_report = self._read_source_report()
        target_rows = _extract_target_rows(source_report)
        source_run_id = str(source_report.get("run_id") or "") or None

        if not target_rows:
            report = AIReport(
                source_run_id=source_run_id,
                status="unavailable",
                portfolio_summary_ko="최종 추천 대상(TOP5)이 없어 AI 리포트를 생성하지 못했습니다.",
                warnings=["AI_REPORT_NO_TARGETS"],
                error_code="AI_REPORT_NO_TARGETS",
            )
            self._persist(report)
            return report

        if not self.api_configured():
            report = AIReport(
                source_run_id=source_run_id,
                status="unavailable",
                portfolio_summary_ko="GLM API Key가 없어 AI 리포트를 생성하지 못했습니다.",
                warnings=["GLM_API_KEY_MISSING"],
                error_code="GLM_API_KEY_MISSING",
            )
            self._persist(report)
            return report

        warnings: list[str] = []
        packet_by_symbol: dict[str, dict[str, Any]] = {}
        for row in target_rows:
            self._touch_runtime_if_running()
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            packet_by_symbol[symbol] = {
                "symbol": symbol,
                "internal": row.get("internal", {}),
                "evidence": self._collect_evidence(symbol, row.get("internal", {}), warnings),
            }

        glm_client = GLMClient.from_env()
        if glm_client is None:
            report = AIReport(
                source_run_id=source_run_id,
                status="unavailable",
                portfolio_summary_ko="GLM 클라이언트를 초기화하지 못했습니다.",
                warnings=warnings + ["GLM_CLIENT_INIT_FAILED"],
                error_code="GLM_CLIENT_INIT_FAILED",
            )
            self._persist(report)
            return report

        system_prompt, user_prompt = _build_glm_prompts(
            [_compact_packet(item) for item in packet_by_symbol.values()]
        )
        self._touch_runtime_if_running()
        try:
            raw = glm_client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
            symbol_rows, portfolio_summary, parse_warnings = _parse_glm_output(
                raw=raw,
                expected_symbols=list(packet_by_symbol.keys()),
            )
            warnings.extend(parse_warnings)
        except GLMClientError as exc:
            report = AIReport(
                source_run_id=source_run_id,
                status="unavailable",
                model=glm_client.model,
                portfolio_summary_ko="GLM 호출 실패로 AI 리포트를 생성하지 못했습니다.",
                warnings=warnings + [str(exc)],
                error_code=str(exc),
            )
            self._persist(report)
            return report

        symbol_decisions: list[AISymbolDecision] = []
        row_map = {str(item.get("symbol") or "").upper(): item for item in symbol_rows}
        for symbol, packet in packet_by_symbol.items():
            parsed_row = row_map.get(symbol)
            if not parsed_row:
                parsed_row = {
                    "symbol": symbol,
                    "decision": "WATCH",
                    "confidence_0_1": 0.5,
                    "score_0_100": 50.0,
                    "summary_ko": "모델 응답에 종목 결과가 없어 관망으로 처리했습니다.",
                    "reasons_ko": ["모델 응답 누락"],
                    "risks_ko": ["응답 품질 확인 필요"],
                }
                warnings.append(f"GLM_MISSING_SYMBOL_RESULT:{symbol}")
            symbol_decisions.append(
                AISymbolDecision(
                    symbol=symbol,
                    decision=_coerce_decision(parsed_row.get("decision")),
                    confidence_0_1=_coerce_float(parsed_row.get("confidence_0_1"), 0.5, 0.0, 1.0),
                    score_0_100=_coerce_float(parsed_row.get("score_0_100"), 50.0, 0.0, 100.0),
                    summary_ko=str(parsed_row.get("summary_ko") or ""),
                    reasons_ko=_coerce_list(parsed_row.get("reasons_ko")),
                    risks_ko=_coerce_list(parsed_row.get("risks_ko")),
                    evidence=[
                        EvidenceItem(
                            source=str(e.get("source") or "internal"),  # type: ignore[arg-type]
                            url=str(e.get("url") or ""),
                            metrics=e.get("metrics", {}) if isinstance(e.get("metrics"), dict) else {},
                        )
                        for e in packet.get("evidence", [])
                        if isinstance(e, dict)
                    ],
                )
            )

        report = AIReport(
            source_run_id=source_run_id,
            provider="glm",
            model=glm_client.model,
            status="ok",
            symbols=symbol_decisions,
            portfolio_summary_ko=portfolio_summary,
            warnings=warnings,
        )
        self._persist(report)
        return report

    def _read_source_report(self) -> dict[str, Any]:
        if not self.source_report_path.exists():
            return {}
        try:
            payload = json.loads(self.source_report_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("failed to read source report path=%s", self.source_report_path, exc_info=True)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _persist(self, report: AIReport) -> None:
        self.ai_report_path.parent.mkdir(parents=True, exist_ok=True)
        self.ai_history_dir.mkdir(parents=True, exist_ok=True)
        serialized = report.model_dump_json(indent=2, ensure_ascii=False)
        self.ai_report_path.write_text(serialized, encoding="utf-8")
        history_path = self.ai_history_dir / f"{report.run_id}.json"
        history_path.write_text(serialized, encoding="utf-8")
        prune_history_files(
            self.ai_history_dir,
            max_files=self.ai_history_max_files,
            max_age_days=self.ai_history_max_days,
            logger=logger,
        )

    def _write_runtime(self, payload: dict[str, Any]) -> None:
        self.ai_runtime_path.parent.mkdir(parents=True, exist_ok=True)
        self.ai_runtime_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _touch_runtime_if_running(self) -> None:
        if not self.ai_runtime_path.exists():
            return
        try:
            payload = json.loads(self.ai_runtime_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("failed to parse runtime heartbeat path=%s", self.ai_runtime_path, exc_info=True)
            return
        if not isinstance(payload, dict):
            return
        if str(payload.get("status") or "").lower() != "running":
            return
        payload["updated_at"] = _now_iso()
        self._write_runtime(payload)

    def _is_runtime_stale(self, payload: dict[str, Any]) -> bool:
        reference = str(payload.get("updated_at") or payload.get("started_at") or "").strip()
        if not reference:
            return True
        parsed = _parse_iso_datetime(reference)
        if parsed is None:
            return True
        now = datetime.now(timezone.utc)
        return (now - parsed).total_seconds() > float(self._effective_running_ttl_sec())

    def _effective_running_ttl_sec(self) -> int:
        base_ttl = int(self.running_ttl_sec)
        timeout_sec = _coerce_int_env("GLM_TIMEOUT_SEC", default=90, min_value=15, max_value=180)
        max_retries = _coerce_int_env("GLM_MAX_RETRIES", default=2, min_value=0, max_value=4)

        # chat_json() can invoke _post() up to two times (response_format 시도 + fallback).
        retry_wait = 0.8 * (max_retries * (max_retries + 1) / 2)
        single_post_worst = timeout_sec * (max_retries + 1) + retry_wait
        glm_worst = single_post_worst * 2

        # Add fixed buffer for evidence collection + serialization overhead.
        adaptive_ttl = int(glm_worst + 180)
        # Keep stale recovery bounded to avoid queued/running state appearing frozen for too long.
        return min(max(base_ttl, adaptive_ttl), 900)

    def _recover_runtime_from_latest_report(self, runtime_payload: dict[str, Any]) -> bool:
        latest = self.read_latest()
        if not isinstance(latest, dict):
            return False

        latest_run_id = str(latest.get("run_id") or "").strip()
        latest_created_raw = str(latest.get("created_at") or "").strip()
        if not latest_run_id or not latest_created_raw:
            return False

        latest_created = _parse_iso_datetime(latest_created_raw)
        if latest_created is None:
            return False

        runtime_started_raw = str(
            runtime_payload.get("started_at") or runtime_payload.get("updated_at") or ""
        ).strip()
        runtime_started = _parse_iso_datetime(runtime_started_raw) if runtime_started_raw else None
        if runtime_started is not None and latest_created < runtime_started:
            return False

        runtime_payload["status"] = "idle"
        runtime_payload["finished_at"] = latest_created_raw
        runtime_payload["updated_at"] = latest_created_raw
        runtime_payload["last_report_run_id"] = latest_run_id
        runtime_payload["last_report_status"] = str(latest.get("status") or "").strip() or None
        runtime_payload["last_error_code"] = str(latest.get("error_code") or "").strip() or None
        self._write_runtime(runtime_payload)
        return True

    def _collect_evidence(
        self,
        symbol: str,
        internal_metrics: dict[str, Any],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        if internal_metrics:
            evidence.append(
                {
                    "source": "internal",
                    "url": "/dashboard",
                    "metrics": internal_metrics,
                }
            )

        yahoo_ok = False
        stooq_ok = False
        yahoo_error: str | None = None
        stooq_error: str | None = None

        try:
            evidence.append(self.yahoo_client.fetch_quote(symbol))
            yahoo_ok = True
        except Exception as exc:
            yahoo_error = f"YAHOO_FAIL:{symbol}:{exc}"
            logger.warning("yahoo evidence fetch failed symbol=%s error=%s", symbol, exc)

        if not yahoo_ok:
            try:
                evidence.append(self.stooq_client.fetch_quote(symbol))
                stooq_ok = True
            except Exception as exc:
                stooq_error = f"STOOQ_FAIL:{symbol}:{exc}"
                logger.warning("stooq evidence fetch failed symbol=%s error=%s", symbol, exc)

        if not yahoo_ok and not stooq_ok:
            if yahoo_error:
                warnings.append(yahoo_error)
            if stooq_error:
                warnings.append(stooq_error)
            fmp_client = FMPClient.from_env()
            if fmp_client is not None:
                try:
                    rows = fmp_client.fetch_quotes([symbol])
                    if rows and isinstance(rows[0], dict):
                        row = rows[0]
                        evidence.append(
                            {
                                "source": "fmp",
                                "url": f"{fmp_client.base_url}/quote?symbol={symbol}",
                                "metrics": {
                                    "price": _coerce_float(row.get("price"), None, None, None),
                                    "change_pct": _coerce_float(
                                        row.get("changePercentage", row.get("changesPercentage")),
                                        None,
                                        None,
                                        None,
                                    ),
                                    "volume": _coerce_float(row.get("volume"), None, None, None),
                                    "market_cap": _coerce_float(row.get("marketCap"), None, None, None),
                                    "pe": _coerce_float(row.get("pe"), None, None, None),
                                },
                            }
                        )
                except Exception as exc:
                    logger.warning("fmp evidence fetch failed symbol=%s error=%s", symbol, exc)
                    warnings.append(f"FMP_FAIL:{symbol}:{exc}")

        # Always include search evidence when MCP client is available.
        if self.zai_search_client is not None:
            try:
                evidence.extend(self.zai_search_client.search_symbol_evidence(symbol))
            except Exception as exc:
                logger.warning("zai search evidence fetch failed symbol=%s error=%s", symbol, exc)
                warnings.append(f"ZAI_SEARCH_FAIL:{symbol}:{exc}")
        return evidence


def _extract_target_rows(source_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pipeline = source_report.get("pipeline")
    if isinstance(pipeline, dict):
        final_summary = pipeline.get("final_summary")
        top5 = final_summary.get("top5_from_top10") if isinstance(final_summary, dict) else None
        if isinstance(top5, list):
            for row in top5[:5]:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                if not symbol:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "internal": {
                            "final_score": _coerce_float(row.get("final_score"), 0.0, None, None),
                            "support_count": int(_coerce_float(row.get("support_count"), 0.0, None, None) or 0),
                            "analyzer_avg_score": _coerce_float(row.get("analyzer_avg_score"), 0.0, None, None),
                        },
                    }
                )
    if rows:
        return rows[:5]

    top_picks = source_report.get("top_picks")
    if isinstance(top_picks, list):
        for row in top_picks[:5]:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "internal": {
                        "top_pick_score": _coerce_float(row.get("score"), 0.0, None, None),
                        "top_pick_reason": str(row.get("reason") or ""),
                    },
                }
            )
    return rows[:5]


def _build_glm_prompts(packets: list[dict[str, Any]]) -> tuple[str, str]:
    schema_hint = {
        "portfolio_summary_ko": "string",
        "symbols": [
            {
                "symbol": "string",
                "decision": "BUY|WATCH|AVOID",
                "confidence_0_1": "number(0~1)",
                "score_0_100": "number(0~100)",
                "summary_ko": "string",
                "reasons_ko": ["string"],
                "risks_ko": ["string"],
            }
        ],
    }
    system_prompt = (
        "너는 미국 주식 최종 판정 분석기다. "
        "입력된 근거만 사용해 JSON만 출력한다. "
        "과도한 확신을 금지하고, BUY/WATCH/AVOID 3단계로 판정한다. "
        "투자 자문이 아닌 참고 분석 문체로 한국어 작성."
    )
    user_prompt = (
        "다음 종목 데이터를 분석해 JSON으로 응답해줘.\n"
        f"출력 스키마: {json.dumps(schema_hint, ensure_ascii=False)}\n"
        "규칙:\n"
        "1) Yahoo 우선 근거를 반영하되, 보조 소스가 있으면 함께 반영\n"
        "1-1) zai_search_mcp 소스가 있으면 최신 뉴스 이벤트를 정성 근거로 반영\n"
        "2) 근거 부족 시 WATCH로 보수적으로 판정\n"
        "3) reasons_ko/risks_ko는 각 2개 이상\n"
        "4) symbols 배열에는 입력된 종목을 모두 포함\n"
        f"입력 데이터: {json.dumps(packets, ensure_ascii=False)}"
    )
    return system_prompt, user_prompt


def _compact_packet(packet: dict[str, Any]) -> dict[str, Any]:
    symbol = str(packet.get("symbol") or "").upper()
    internal = packet.get("internal", {}) if isinstance(packet.get("internal"), dict) else {}
    evidence_rows = packet.get("evidence", []) if isinstance(packet.get("evidence"), list) else []

    compact_evidence: list[dict[str, Any]] = []
    for row in evidence_rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {}
        selected_metrics: dict[str, Any] = {}
        for key in (
            "price",
            "change_pct",
            "volume",
            "market_cap",
            "trailing_pe",
            "pe",
            "close",
            "final_score",
            "support_count",
            "analyzer_avg_score",
            "top_pick_score",
            "title",
            "snippet",
            "publish_date",
            "media",
        ):
            if key not in metrics:
                continue
            value = metrics.get(key)
            if value is None or value == "":
                continue
            selected_metrics[key] = value
        compact_evidence.append(
            {
                "source": source,
                "url": str(row.get("url") or "")[:180],
                "metrics": selected_metrics,
            }
        )

    compact_internal = {
        key: value
        for key, value in internal.items()
        if key in {"final_score", "support_count", "analyzer_avg_score", "top_pick_score"}
    }

    return {
        "symbol": symbol,
        "internal": compact_internal,
        "evidence": compact_evidence[:3],
    }


def _parse_glm_output(raw: dict[str, Any], expected_symbols: list[str]) -> tuple[list[dict[str, Any]], str, list[str]]:
    warnings: list[str] = []
    symbols_raw = raw.get("symbols")
    if not isinstance(symbols_raw, list):
        symbols_raw = []
        warnings.append("GLM_SYMBOLS_NOT_LIST")
    symbols: list[dict[str, Any]] = []
    expected_set = {str(item).upper() for item in expected_symbols}
    for row in symbols_raw:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol and symbol not in expected_set:
            continue
        if symbol:
            symbols.append(
                {
                    "symbol": symbol,
                    "decision": _coerce_decision(row.get("decision")),
                    "confidence_0_1": _coerce_float(row.get("confidence_0_1"), 0.5, 0.0, 1.0),
                    "score_0_100": _coerce_float(row.get("score_0_100"), 50.0, 0.0, 100.0),
                    "summary_ko": str(row.get("summary_ko") or ""),
                    "reasons_ko": _coerce_list(row.get("reasons_ko")),
                    "risks_ko": _coerce_list(row.get("risks_ko")),
                }
            )
    summary = str(raw.get("portfolio_summary_ko") or "")
    if not summary:
        summary = "AI 포트폴리오 요약이 제공되지 않았습니다."
    return symbols, summary, warnings


def _coerce_decision(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"BUY", "WATCH", "AVOID"}:
        return text
    return "WATCH"


def _coerce_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value[:10]:
        text = str(item or "").strip()
        if text:
            output.append(text)
    return output


def _coerce_float(
    value: Any,
    default: float | None,
    min_value: float | None,
    max_value: float | None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(text: str) -> datetime | None:
    value = str(text or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))
