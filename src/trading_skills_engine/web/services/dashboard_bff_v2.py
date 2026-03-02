from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from trading_skills_engine.ai.report_service import AIReportService
from trading_skills_engine.config.fmp_runtime import get_fmp_runtime_state
from trading_skills_engine.config.market_scope_runtime import get_market_scope_runtime_state
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.registry import is_implemented, is_recommendation_capable
from trading_skills_engine.skills_v2.traits import get_skill_trait

DEFAULT_REPORT_PATH = Path("reports/skill_runs/latest_skill_runs_v2.json")
DEFAULT_APP_NAME = "Coreline Stock AI"
SKILL_DETAIL_REFERENCE_PATH = Path(__file__).resolve().with_name("skill_detail_reference.json")

DEFAULT_PARAMS_BY_SKILL: dict[str, dict[str, Any]] = {
    "top-picks": {
        "mode": "two_stage_intersection",
        "recommender_top_n": 25,
    },
}

KOREAN_SYMBOL_ALIASES: dict[str, str] = {
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
    "NVDA": "엔비디아",
    "AMZN": "아마존",
    "META": "메타",
    "GOOGL": "알파벳",
    "TSLA": "테슬라",
    "AVGO": "브로드컴",
    "AMD": "AMD",
    "INTC": "인텔",
    "QCOM": "퀄컴",
    "NFLX": "넷플릭스",
    "SPY": "S&P500 ETF",
    "QQQ": "나스닥100 ETF",
    "IWM": "러셀2000 ETF",
    "TLT": "미국 장기채 ETF",
    "GLD": "금 ETF",
    "XOM": "엑슨모빌",
    "JPM": "JP모건",
    "LLY": "일라이 릴리",
    "COST": "코스트코",
    "PLTR": "팔란티어",
    "SMCI": "슈퍼마이크로컴퓨터",
    "SOXX": "반도체 ETF",
    "TAC": "트랜스알타",
    "ABCL": "앱셀레라 바이오로직스",
    "AI": "C3.ai",
    "MP": "MP 머티리얼즈",
    "JOBY": "조비 에비에이션",
    "DCI": "도널드슨",
    "STNE": "스톤코",
    "ADT": "ADT",
    "XPOF": "엑스포넨셜 피트니스",
    "SBA": "SBA 커뮤니케이션스",
    "SBAC": "SBA 커뮤니케이션스",
    "RPID": "래피드 마이크로 바이오시스템즈",
    "SHAK": "쉐이크쉑",
    "ARQT": "아르쿠티스 바이오테라퓨틱스",
    "QURE": "유니큐어",
    "LNG": "셰니어 에너지",
}

KOREAN_COMPANY_ALIASES: dict[str, str] = {
    "Apple": "애플",
    "Microsoft": "마이크로소프트",
    "NVIDIA": "엔비디아",
    "Amazon": "아마존",
    "Meta": "메타",
    "Alphabet": "알파벳",
    "Tesla": "테슬라",
    "Broadcom": "브로드컴",
    "Intel": "인텔",
    "Qualcomm": "퀄컴",
    "Netflix": "넷플릭스",
    "JPMorgan": "JP모건",
    "Exxon Mobil": "엑슨모빌",
    "Eli Lilly": "일라이 릴리",
    "Costco": "코스트코",
    "TransAlta": "트랜스알타",
    "AbCellera Biologics": "앱셀레라 바이오로직스",
    "C3.ai": "C3.ai",
    "MP Materials": "MP 머티리얼즈",
    "Joby Aviation": "조비 에비에이션",
    "Donaldson": "도널드슨",
    "StoneCo": "스톤코",
    "ADT": "ADT",
    "SBA Communications": "SBA 커뮤니케이션스",
    "Shake Shack": "쉐이크쉑",
    "uniQure": "유니큐어",
    "Cheniere Energy": "셰니어 에너지",
}

COMPANY_KO_TOKEN_ALIASES: dict[str, str] = {
    "AMERICAN": "아메리칸",
    "AIR": "에어",
    "AIRLINES": "에어라인즈",
    "ATLANTIC": "애틀랜틱",
    "PACIFIC": "퍼시픽",
    "APPLIED": "어플라이드",
    "OPTICAL": "옵티컬",
    "OPTOELECTRONICS": "옵토일렉트로닉스",
    "ACQUISITION": "어퀴지션",
    "ACQUISITIONS": "어퀴지션스",
    "ORDINARY": "오디너리",
    "SHARE": "셰어",
    "SHARES": "셰어즈",
    "CLASS": "클래스",
    "STOCK": "스톡",
    "TRADING": "트레이딩",
    "BANK": "뱅크",
    "BANCORP": "뱅코프",
    "FINANCE": "파이낸스",
    "RETAIL": "리테일",
    "INDUSTRIALS": "인더스트리얼스",
    "ELECTRONIC": "일렉트로닉",
    "FOODS": "푸즈",
    "FOOD": "푸드",
    "PHARMA": "파마",
    "TECHNOLOGY": "테크놀로지",
    "TECHNOLOGIES": "테크놀로지스",
    "THERAPEUTICS": "테라퓨틱스",
    "PHARMACEUTICALS": "파마슈티컬스",
    "BIOTECH": "바이오테크",
    "BIOTECHNOLOGY": "바이오테크놀로지",
    "BIOSCIENCE": "바이오사이언스",
    "BIOSCIENCES": "바이오사이언스",
    "BIOLOGICS": "바이오로직스",
    "BIO": "바이오",
    "MEDICAL": "메디컬",
    "HEALTH": "헬스",
    "HEALTHCARE": "헬스케어",
    "COMMUNICATION": "커뮤니케이션",
    "COMMUNICATIONS": "커뮤니케이션즈",
    "SOFTWARE": "소프트웨어",
    "SYSTEM": "시스템",
    "SYSTEMS": "시스템즈",
    "NETWORK": "네트워크",
    "NETWORKS": "네트웍스",
    "ENERGY": "에너지",
    "MATERIALS": "머티리얼즈",
    "INDUSTRIES": "인더스트리즈",
    "INDUSTRIAL": "인더스트리얼",
    "DYNAMICS": "다이내믹스",
    "GLOBAL": "글로벌",
    "INTERNATIONAL": "인터내셔널",
    "GROUP": "그룹",
    "HOLDING": "홀딩",
    "HOLDINGS": "홀딩스",
    "CAPITAL": "캐피털",
    "FINANCIAL": "파이낸셜",
    "ROBOTICS": "로보틱스",
    "SEMICONDUCTOR": "세미컨덕터",
    "SEMICONDUCTORS": "세미컨덕터",
    "MOTOR": "모터",
    "MOTORS": "모터스",
    "ELECTRIC": "일렉트릭",
    "ELECTRONICS": "일렉트로닉스",
    "AEROSPACE": "에어로스페이스",
    "VENTURES": "벤처스",
    "ANALYTICS": "애널리틱스",
    "DIGITAL": "디지털",
    "MEDIA": "미디어",
    "CLOUD": "클라우드",
    "AI": "에이아이",
    "DATA": "데이터",
    "LAB": "랩",
    "LABS": "랩스",
    "LABORATORIES": "래버러토리스",
}

GENERIC_COMPANY_KO_TOKENS: set[str] = {
    "그룹",
    "홀딩",
    "홀딩스",
    "인터내셔널",
    "글로벌",
    "캐피털",
    "파이낸셜",
    "커뮤니케이션",
    "커뮤니케이션즈",
}

COMPANY_NAME_CLEANUP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\(.*?\)"),
    re.compile(r"\bcommon stock\b.*", re.IGNORECASE),
    re.compile(r"\bordinary shares?\b.*", re.IGNORECASE),
    re.compile(r"\bdepositary shares?\b.*", re.IGNORECASE),
    re.compile(r"\bclass\s+[a-z]\b.*", re.IGNORECASE),
)

COMPANY_NOISE_TOKENS: set[str] = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "LIMITED",
    "PLC",
    "LP",
    "LLC",
    "NV",
    "SA",
    "THE",
}

KOREAN_TICKER_LETTER_NAMES: dict[str, str] = {
    "A": "에이",
    "B": "비",
    "C": "씨",
    "D": "디",
    "E": "이",
    "F": "에프",
    "G": "지",
    "H": "에이치",
    "I": "아이",
    "J": "제이",
    "K": "케이",
    "L": "엘",
    "M": "엠",
    "N": "엔",
    "O": "오",
    "P": "피",
    "Q": "큐",
    "R": "알",
    "S": "에스",
    "T": "티",
    "U": "유",
    "V": "브이",
    "W": "더블유",
    "X": "엑스",
    "Y": "와이",
    "Z": "지",
}


class DashboardBFFV2:
    def __init__(self, report_path: Path | None = None) -> None:
        env_path = os.getenv("SKILL_RUN_REPORT_V2_PATH")
        self.report_path = Path(env_path) if env_path else (report_path or DEFAULT_REPORT_PATH)
        self.ai_report_service = AIReportService(source_report_path=self.report_path)

    def get_dashboard_view_model(self) -> dict[str, Any]:
        report = self._load_report()
        market_scope_runtime = get_market_scope_runtime_state()
        runtime_scope = str(market_scope_runtime.get("scope") or "US")
        universe_meta = _normalize_universe_meta(report.get("universe_meta"), runtime_scope)
        results = report["results"]
        selected_slugs = {str(item.get("skill_slug")) for item in results if isinstance(item, dict)}
        raw_pipeline = report.get("pipeline", {})
        inferred_mode = _infer_top_picks_mode(report.get("top_picks", []), raw_pipeline)
        params_defaults = _params_defaults_with_mode(inferred_mode, raw_pipeline)
        detail_reference_map = _load_skill_detail_reference_map()

        catalog: list[dict[str, Any]] = []
        for item in SKILL_CATALOG:
            trait = get_skill_trait(item.slug)
            trait_role = trait.recommendation_role if trait else "analysis_only"
            trait_style = trait.style if trait else item.family
            ref = detail_reference_map.get(item.slug, {})
            catalog.append(
                {
                    "slug": item.slug,
                    "display_name": item.display_name,
                    "family": item.family,
                    "family_ko": _family_label_ko(item.family),
                    "methodology": item.methodology,
                    "implemented": is_implemented(item.slug),
                    "recommendation_capable": is_recommendation_capable(item.slug, mode=inferred_mode),
                    "trait_role": trait_role,
                    "role_ko": _role_label_ko(trait_role),
                    "trait_style": trait_style,
                    "trait_signals": list((trait.signals or ())) if trait else [],
                    "trait_axes": dict(trait.axis_weights or {}) if trait else {},
                    "uses_llm": bool(item.uses_llm),
                    "uses_llm_ko": _bool_label_ko(bool(item.uses_llm)),
                    "requires_api": bool(item.requires_api),
                    "requires_api_ko": _api_required_label_ko(bool(item.requires_api)),
                    "reference_overview": str(ref.get("overview") or ""),
                    "reference_when_to_use": str(ref.get("when_to_use") or ""),
                    "reference_data_sources": str(ref.get("data_sources") or ""),
                    "reference_workflow": str(ref.get("workflow") or ""),
                    "reference_output": str(ref.get("output") or ""),
                    "reference_prerequisites": str(ref.get("prerequisites") or ""),
                    "reference_source": str(ref.get("source") or ""),
                    "reference_source_url": str(ref.get("source_url") or ""),
                    "selected": item.slug in selected_slugs,
                }
            )
        catalog_by_slug = {item["slug"]: item for item in catalog}
        skill_detail_map: dict[str, dict[str, Any]] = {}
        for item in catalog:
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            skill_detail_map[slug] = {
                "display_name": item.get("display_name", ""),
                "slug": slug,
                "family": item.get("family", ""),
                "family_ko": item.get("family_ko", ""),
                "role": item.get("trait_role", ""),
                "role_ko": item.get("role_ko", ""),
                "style": item.get("trait_style", ""),
                "methodology": item.get("methodology", ""),
                "signals": item.get("trait_signals", []),
                "axes": item.get("trait_axes", {}),
                "uses_llm_ko": item.get("uses_llm_ko", ""),
                "requires_api_ko": item.get("requires_api_ko", ""),
                "reference_overview": item.get("reference_overview", ""),
                "reference_when_to_use": item.get("reference_when_to_use", ""),
                "reference_data_sources": item.get("reference_data_sources", ""),
                "reference_workflow": item.get("reference_workflow", ""),
                "reference_output": item.get("reference_output", ""),
                "reference_prerequisites": item.get("reference_prerequisites", ""),
                "reference_source": item.get("reference_source", ""),
                "reference_source_url": item.get("reference_source_url", ""),
            }

        results_enriched: list[dict[str, Any]] = []
        for raw in results:
            if not isinstance(raw, dict):
                continue
            slug = str(raw.get("skill_slug") or "")
            meta = catalog_by_slug.get(slug, {})
            results_enriched.append(
                {
                    **raw,
                    "display_name": meta.get("display_name", slug),
                    "family": meta.get("family", "-"),
                }
            )

        top_picks = _normalize_top_picks(report.get("top_picks", []))
        pipeline_tables = _normalize_pipeline(report.get("pipeline", {}))
        _decorate_pipeline_tables(pipeline_tables, catalog_by_slug)
        ai_runtime = _build_ai_runtime(
            source_report=report,
            ai_report_service=self.ai_report_service,
        )
        ai_symbols: list[str] = []
        latest_ai_report = ai_runtime.get("latest_report")
        if isinstance(latest_ai_report, dict):
            for row in latest_ai_report.get("symbols", []):
                if isinstance(row, dict):
                    symbol = str(row.get("symbol") or "").strip().upper()
                    if symbol:
                        ai_symbols.append(symbol)

        symbol_name_ko = _build_symbol_name_ko_map(
            top_picks=top_picks,
            pipeline_tables=pipeline_tables,
            results=results_enriched,
            scope=str((report.get("universe_meta") or {}).get("scope") or "US"),
            ai_symbols=ai_symbols,
        )
        selected_skill_top5 = _build_selected_skill_top5(results_enriched)
        final_intersection_top5 = _build_final_intersection_top5(pipeline_tables)
        recommender_list = [item for item in catalog if item["trait_role"] in {"direct", "candidate"}]
        analyzer_list = [item for item in catalog if item["trait_role"] == "analysis_only"]
        selected_recommender_count = sum(1 for item in recommender_list if item.get("selected"))
        selected_analyzer_count = sum(1 for item in analyzer_list if item.get("selected"))

        return {
            "header": {
                "app_name": DEFAULT_APP_NAME,
                "as_of_date": report["as_of_date"],
            },
            "date_display_ko": _format_ko_date(report["as_of_date"]),
            "fmp_runtime": get_fmp_runtime_state(),
            "market_scope_runtime": market_scope_runtime,
            "data_sources": report.get("data_sources", {"fmp": "unavailable", "rss": "unavailable"}),
            "universe_meta": universe_meta,
            "warnings": report.get("warnings", []),
            "skill_catalog": catalog,
            "skill_detail_map": skill_detail_map,
            "results": results_enriched,
            "top_picks": top_picks,
            "pipeline_tables": pipeline_tables,
            "symbol_name_ko": symbol_name_ko,
            "summary_top5": {
                "selected_skill_scores": selected_skill_top5,
                "final_intersection": final_intersection_top5,
            },
            "ai_runtime": ai_runtime,
            "left_menu": {
                "recommender_skills": recommender_list,
                "analyzer_skills": analyzer_list,
                "selected_recommender_count": selected_recommender_count,
                "selected_analyzer_count": selected_analyzer_count,
                "max_recommender": 5,
                "max_analyzer": 3,
                "single_ticker": "",
                "multi_tickers": "",
            },
            "risk_badges": ["투자 권유 아님", "무효화 레벨 확인"],
            "recommendation_mode": inferred_mode,
            "recommendation_summary": {
                "selected_recommendation_count": sum(
                    1 for item in catalog if item["selected"] and item["recommendation_capable"]
                ),
                "selected_analysis_only_count": sum(
                    1 for item in catalog if item["selected"] and not item["recommendation_capable"]
                ),
                "total_recommendation_capable_count": sum(1 for item in catalog if item["recommendation_capable"]),
            },
            "result_counts": {
                "ok": sum(1 for item in results_enriched if item.get("status") == "ok"),
                "unavailable": sum(1 for item in results_enriched if item.get("status") == "unavailable"),
                "not_implemented": sum(1 for item in results_enriched if item.get("status") == "not_implemented"),
            },
            "params_defaults": params_defaults,
            "selected_skill_count": len(selected_slugs),
            "role_groups": {
                "recommendation": [
                    item["slug"] for item in catalog if item["trait_role"] in {"direct", "candidate"}
                ],
                "analysis": [item["slug"] for item in catalog if item["trait_role"] == "analysis_only"],
            },
        }

    def _load_report(self) -> dict[str, Any]:
        if not self.report_path.exists():
            return _empty_report()

        try:
            payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        except Exception:
            return _empty_report()

        if not isinstance(payload, dict):
            return _empty_report()

        results = payload.get("results")
        top_picks = payload.get("top_picks")
        pipeline = payload.get("pipeline")

        return {
            "as_of_date": _parse_iso_date(str(payload.get("as_of_date") or date.today().isoformat())),
            "data_sources": payload.get("data_sources", {"fmp": "unavailable", "rss": "unavailable"}),
            "universe_meta": payload.get(
                "universe_meta",
                {
                    "scope": get_market_scope_runtime_state().get("scope") or "US",
                    "source": "unavailable",
                    "source_provider": "",
                    "universe_mode": (
                        "KOSPI500_KOSDAQ200"
                        if str(get_market_scope_runtime_state().get("scope") or "US") == "KR"
                        else "SP500_PLUS_NASDAQ_TOP500"
                    ),
                    "raw_count": 0,
                    "filtered_count": 0,
                    "selected_count": 0,
                    "sp500_count": 0,
                    "nasdaq_top500_count": 0,
                    "kospi500_count": 0,
                    "kosdaq200_count": 0,
                    "fetched_at": "",
                },
            ),
            "warnings": payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else [],
            "results": results if isinstance(results, list) else [],
            "top_picks": top_picks if isinstance(top_picks, list) else [],
            "pipeline": pipeline if isinstance(pipeline, dict) else {},
        }


def _empty_report() -> dict[str, Any]:
    runtime_scope = str(get_market_scope_runtime_state().get("scope") or "US")
    return {
        "as_of_date": date.today().isoformat(),
        "data_sources": {"fmp": "unavailable", "rss": "unavailable"},
        "universe_meta": {
            "scope": runtime_scope,
            "source": "unavailable",
            "source_provider": "",
            "universe_mode": "KOSPI500_KOSDAQ200" if runtime_scope == "KR" else "SP500_PLUS_NASDAQ_TOP500",
            "raw_count": 0,
            "filtered_count": 0,
            "selected_count": 0,
            "sp500_count": 0,
            "nasdaq_top500_count": 0,
            "kospi500_count": 0,
            "kosdaq200_count": 0,
            "fetched_at": "",
        },
        "warnings": ["아직 v2 실행 결과가 없습니다. 왼쪽에서 스킬을 선택하고 실행하세요."],
        "results": [],
        "top_picks": [],
        "pipeline": {},
    }


def _normalize_universe_meta(raw: Any, runtime_scope: str) -> dict[str, Any]:
    scope = str(runtime_scope or "US").upper()
    default_meta = {
        "scope": scope,
        "source": "unavailable",
        "source_provider": "",
        "universe_mode": "KOSPI500_KOSDAQ200" if scope == "KR" else "SP500_PLUS_NASDAQ_TOP500",
        "ranking_basis": "",
        "raw_count": 0,
        "filtered_count": 0,
        "selected_count": 0,
        "sp500_count": 0,
        "nasdaq_top500_count": 0,
        "kospi500_count": 0,
        "kosdaq200_count": 0,
        "fetched_at": "",
    }
    if not isinstance(raw, dict):
        return default_meta

    source_scope = str(raw.get("scope") or "").upper()
    if source_scope and source_scope != scope:
        # 스코프 전환 직후에는 이전 리포트 메타를 숨기고 현재 스코프 기준으로 초기화한다.
        return default_meta

    merged = dict(default_meta)
    merged.update(raw)
    merged["scope"] = scope
    return merged


def _parse_iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return date.today().isoformat()


def _format_ko_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return "-"
    return parsed.strftime("%Y. %m. %d.")


def _normalize_top_picks(raw_picks: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_picks:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        normalized.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or ""),
                "sector": str(item.get("sector") or ""),
                "return_pct": _to_float(item.get("return_pct"), 0.0),
                "reason": str(item.get("reason") or ""),
                "score": _to_float(item.get("score"), 0.0),
                "decision": _normalize_decision(item.get("decision")),
                "primary_skill": str(item.get("primary_skill") or ""),
                "confirm_votes": _to_int(item.get("confirm_votes"), 0),
                "confirm_required": _to_int(item.get("confirm_required"), 0),
                "veto_count": _to_int(item.get("veto_count"), 0),
                "confirm_hits": _to_str_list(item.get("confirm_hits")),
                "veto_skills": _to_str_list(item.get("veto_skills")),
            }
        )
    return normalized


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _to_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    parsed: list[str] = []
    for item in value[:20]:
        text = str(item).strip()
        if not text:
            continue
        parsed.append(text)
    return parsed


def _normalize_decision(value: Any) -> str:
    decision = str(value or "").upper()
    if decision in {"PASS", "WATCH", "REJECT"}:
        return decision
    return ""


def _infer_top_picks_mode(top_picks: list[Any], pipeline: Any = None) -> str:
    if isinstance(pipeline, dict) and pipeline:
        if isinstance(pipeline.get("recommender_outputs"), list):
            return "two_stage_intersection"
    if not top_picks:
        return "skill_consensus"
    first = top_picks[0] if isinstance(top_picks[0], dict) else {}
    reason = str(first.get("reason") or "").lower()
    if "role gated" in reason:
        return "role_gated_consensus"
    if "two-stage strict intersection" in reason:
        return "two_stage_intersection"
    if "watchlist consensus" in reason:
        return "watchlist_consensus"
    return "skill_consensus"


def _params_defaults_with_mode(mode: str, pipeline: Any = None) -> dict[str, dict[str, Any]]:
    defaults = {
        key: dict(value) for key, value in DEFAULT_PARAMS_BY_SKILL.items()
    }
    top_picks = defaults.get("top-picks", {})
    top_picks["mode"] = "two_stage_intersection"
    top_picks["recommender_top_n"] = 25
    defaults["top-picks"] = top_picks
    return defaults


def _normalize_pipeline(raw_pipeline: Any) -> dict[str, Any]:
    if not isinstance(raw_pipeline, dict):
        return {
            "recommender_outputs": [],
            "recommender_intersection": {"symbols": [], "support_count_by_symbol": {}, "dropped_by_stage": []},
            "recommender_union_top10": {"symbols": [], "source_union_count": 0},
            "analysis_targets": {"intersection_symbols": [], "top10_symbols": []},
            "analyzer_outputs": [],
            "analyzer_outputs_by_target": [],
            "final_intersection": {"symbols": [], "final_reasons": [], "policy_used": "all_pass", "comparison": {}, "post_analyzer_by_recommender": [], "per_skill_traces": [], "ranking": []},
            "final_summary": {"intersection_symbols": [], "top5_from_top10": [], "policy_used": "all_pass", "dropped_by_stage": []},
            "counts": {"recommender_skills": 0, "recommender_intersection": 0, "recommender_top10": 0, "analyzer_skills": 0, "final_symbols": 0, "final_top5": 0},
            "diagnostics": {"target_groups_identical": False, "uniform_score_items": [], "messages": []},
        }

    recommender_outputs = raw_pipeline.get("recommender_outputs")
    recommender_outputs = recommender_outputs if isinstance(recommender_outputs, list) else []
    recommender_union_top10 = raw_pipeline.get("recommender_union_top10")
    if not isinstance(recommender_union_top10, dict):
        recommender_union_top10 = {"symbols": [], "source_union_count": 0}
    else:
        recommender_union_top10.setdefault("symbols", [])
        recommender_union_top10.setdefault("source_union_count", 0)
    analysis_targets = raw_pipeline.get("analysis_targets")
    if not isinstance(analysis_targets, dict):
        analysis_targets = {"intersection_symbols": [], "top10_symbols": []}
    else:
        analysis_targets.setdefault("intersection_symbols", [])
        analysis_targets.setdefault("top10_symbols", [])
    analyzer_outputs = raw_pipeline.get("analyzer_outputs")
    analyzer_outputs = analyzer_outputs if isinstance(analyzer_outputs, list) else []
    analyzer_outputs_by_target_raw = raw_pipeline.get("analyzer_outputs_by_target")
    analyzer_outputs_by_target_raw = analyzer_outputs_by_target_raw if isinstance(analyzer_outputs_by_target_raw, list) else []
    analyzer_outputs_by_target: list[dict[str, Any]] = []
    for output in analyzer_outputs_by_target_raw:
        if not isinstance(output, dict):
            continue
        evaluations_raw = output.get("evaluations")
        evaluations_raw = evaluations_raw if isinstance(evaluations_raw, list) else []
        evaluations: list[dict[str, Any]] = []
        for row in evaluations_raw:
            if not isinstance(row, dict):
                continue
            decision = _normalize_decision(row.get("decision"))
            reasons = _to_str_list(row.get("reasons"))
            risk_flags = _to_str_list(row.get("risk_flags"))
            reasons_ko = [_humanize_analyzer_reason(item) for item in reasons]
            if not reasons_ko:
                reasons_ko = ["종목별 근거 데이터가 없어 거시 공통 평가로 처리됨"]
            evaluations.append(
                {
                    **row,
                    "decision": decision,
                    "decision_ko": _decision_label_ko(decision),
                    "score": round(_to_float(row.get("score"), 0.0), 2),
                    "reasons": reasons,
                    "reasons_ko": reasons_ko,
                    "risk_flags": risk_flags,
                    "risk_flags_ko": [_humanize_risk_flag(item) for item in risk_flags],
                }
            )
        pass_count = sum(
            1
            for row in evaluations
            if str(row.get("decision") or "").upper() == "PASS"
        )
        watch_count = sum(
            1
            for row in evaluations
            if str(row.get("decision") or "").upper() == "WATCH"
        )
        reject_count = sum(
            1
            for row in evaluations
            if str(row.get("decision") or "").upper() == "REJECT"
        )
        score_values = [
            round(_to_float(row.get("score"), 0.0), 2)
            for row in evaluations
            if isinstance(row, dict)
        ]
        uniform_score = len(score_values) >= 2 and len(set(score_values)) == 1
        analyzer_outputs_by_target.append(
            {
                **output,
                "evaluations": evaluations,
                "summary": {
                    "total": len(evaluations),
                    "pass": pass_count,
                    "watch": watch_count,
                    "reject": reject_count,
                    "uniform_score": uniform_score,
                    "uniform_value": (score_values[0] if uniform_score else None),
                },
            }
        )
    recommender_intersection = raw_pipeline.get("recommender_intersection")
    if not isinstance(recommender_intersection, dict):
        recommender_intersection = {"symbols": [], "support_count_by_symbol": {}, "dropped_by_stage": []}
    final_intersection = raw_pipeline.get("final_intersection")
    if not isinstance(final_intersection, dict):
        final_intersection = {"symbols": [], "final_reasons": [], "policy_used": "all_pass", "comparison": {}, "post_analyzer_by_recommender": [], "per_skill_traces": [], "ranking": []}
    else:
        final_intersection.setdefault("symbols", [])
        final_intersection.setdefault("final_reasons", [])
        final_intersection.setdefault("policy_used", "all_pass")
        final_intersection.setdefault("comparison", {})
        final_intersection.setdefault("post_analyzer_by_recommender", [])
        final_intersection.setdefault("per_skill_traces", [])
        final_intersection.setdefault("ranking", [])
    final_summary = raw_pipeline.get("final_summary")
    if not isinstance(final_summary, dict):
        final_summary = {"intersection_symbols": [], "top5_from_top10": [], "policy_used": "all_pass", "dropped_by_stage": []}
    else:
        final_summary.setdefault("intersection_symbols", [])
        final_summary.setdefault("top5_from_top10", [])
        final_summary.setdefault("policy_used", "all_pass")
        final_summary.setdefault("dropped_by_stage", [])

    symbols = recommender_intersection.get("symbols")
    final_symbols = final_intersection.get("symbols")
    top10_symbols = recommender_union_top10.get("symbols")
    top5_rows = final_summary.get("top5_from_top10")
    diagnostics = _build_pipeline_diagnostics(
        analysis_targets=analysis_targets,
        recommender_union_top10=recommender_union_top10,
        analyzer_outputs_by_target=analyzer_outputs_by_target,
    )
    return {
        "recommender_outputs": recommender_outputs,
        "recommender_intersection": recommender_intersection,
        "recommender_union_top10": recommender_union_top10,
        "analysis_targets": analysis_targets,
        "analyzer_outputs": analyzer_outputs,
        "analyzer_outputs_by_target": analyzer_outputs_by_target,
        "final_intersection": final_intersection,
        "final_summary": final_summary,
        "diagnostics": diagnostics,
        "counts": {
            "recommender_skills": len(recommender_outputs),
            "recommender_intersection": len(symbols) if isinstance(symbols, list) else 0,
            "analyzer_skills": len(analyzer_outputs),
            "final_symbols": len(final_symbols) if isinstance(final_symbols, list) else 0,
            "recommender_top10": len(top10_symbols) if isinstance(top10_symbols, list) else 0,
            "final_top5": len(top5_rows) if isinstance(top5_rows, list) else 0,
        },
    }


def _decorate_pipeline_tables(
    pipeline_tables: dict[str, Any],
    catalog_by_slug: dict[str, dict[str, Any]],
) -> None:
    union_top10 = pipeline_tables.get("recommender_union_top10")
    if isinstance(union_top10, dict):
        rows = union_top10.get("symbols")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = row.get("normalized_by_skill")
                normalized_items: list[dict[str, Any]] = []
                if isinstance(normalized, dict):
                    for slug, raw_percentile in normalized.items():
                        skill_slug = str(slug or "").strip()
                        if not skill_slug:
                            continue
                        display_name = str(
                            catalog_by_slug.get(skill_slug, {}).get("display_name") or skill_slug
                        )
                        normalized_items.append(
                            {
                                "skill_slug": skill_slug,
                                "display_name": display_name,
                                "percentile": round(_to_float(raw_percentile, 0.0), 2),
                            }
                        )
                normalized_items.sort(
                    key=lambda item: (
                        -float(item.get("percentile", 0.0)),
                        str(item.get("skill_slug", "")),
                    )
                )
                row["normalized_items"] = normalized_items

                reason_items: list[dict[str, Any]] = []
                seen_reason_keys: set[tuple[str, str]] = set()
                reasons = row.get("reasons")
                if isinstance(reasons, list):
                    for raw_reason in reasons:
                        text = str(raw_reason or "").strip()
                        if not text:
                            continue
                        if ":" in text:
                            raw_slug, raw_source = text.split(":", 1)
                        else:
                            raw_slug, raw_source = "", text
                        skill_slug = raw_slug.strip()
                        source_key = raw_source.strip()
                        if not source_key:
                            continue
                        dedup_key = (skill_slug, source_key)
                        if dedup_key in seen_reason_keys:
                            continue
                        seen_reason_keys.add(dedup_key)
                        display_name = (
                            str(catalog_by_slug.get(skill_slug, {}).get("display_name") or skill_slug)
                            if skill_slug
                            else "unknown"
                        )
                        reason_items.append(
                            {
                                "skill_slug": skill_slug,
                                "display_name": display_name,
                                "source_key": source_key,
                                "source_label": _humanize_reason_source(source_key),
                            }
                        )
                row["reason_items"] = reason_items


def _humanize_reason_source(source_key: str) -> str:
    key = str(source_key or "").strip().lower()
    mapping = {
        "top_candidates": "상위 후보 기반",
        "top_candidates_score": "상위 후보 점수값 기반",
        "top_candidates_derived": "상위 후보 파생 점수 기반",
        "leaders_score": "리더 후보 점수 기반",
        "leaders_derived": "리더 후보 파생 점수 기반",
        "candidates_setup": "후보 Setup 점수 기반",
        "candidates_score": "후보 점수 기반",
        "candidates_derived": "후보 파생 점수 기반",
        "ticker": "직접 티커",
        "targets": "포트폴리오 타깃 기반",
        "ranked_events": "뉴스 연관 티커",
        "earnings": "실적 일정 기반",
        "payload_extract": "페이로드 추출",
    }
    return mapping.get(key, key or "-")


def _decision_label_ko(decision: str) -> str:
    mapping = {
        "PASS": "통과",
        "WATCH": "관찰",
        "REJECT": "제외",
    }
    return mapping.get(str(decision or "").upper(), "-")


def _humanize_risk_flag(flag: str) -> str:
    key = str(flag or "").strip().lower()
    mapping = {
        "low_skill_score": "스킬 기본 점수 낮음",
        "low_confidence": "신뢰도 낮음",
        "symbol_signal_absent": "종목별 신호 부족(거시 공통)",
    }
    return mapping.get(key, key or "-")


def _humanize_analyzer_reason(reason: str) -> str:
    text = str(reason or "").strip()
    if not text:
        return "-"

    if text == "symbol matched":
        return "분석 스킬 후보에 포함됨"
    if text == "symbol not matched":
        return "분석 스킬 후보에 미포함"
    if text == "symbol_signal absent":
        return "종목별 신호가 없어 공통 점수 기반으로 평가"

    m = re.match(r"^base\s+([0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"기본 점수 {m.group(1)}"

    m = re.match(r"^confidence\s+([0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"신뢰도 {m.group(1)}"

    m = re.match(r"^rank_bonus\s+([0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"랭크 가산점 {m.group(1)}"

    m = re.match(r"^ai_factor\s+([0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"AI 팩터 {m.group(1)}"

    m = re.match(r"^momentum_20d\s+([\-]?[0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"20일 모멘텀 {m.group(1)}"

    m = re.match(r"^recommender_strength\s+([\-]?[0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"추천 단계 강도 {m.group(1)}"

    m = re.match(r"^strength_adjust\s+([\-]?[0-9]+(?:\.[0-9]+)?)$", text)
    if m:
        return f"강도 보정 {m.group(1)}"

    m = re.match(r"^style\s+([a-z0-9_\-]+)$", text)
    if m:
        style = m.group(1)
        style_map = {
            "cross_asset_regime": "스타일 교차자산 레짐",
            "macro_regime": "스타일 매크로 레짐",
        }
        return style_map.get(style, f"스타일 {style}")

    m = re.match(
        r"^style_weights\s+rank\s+([0-9]+(?:\.[0-9]+)?)\s+ai\s+([0-9]+(?:\.[0-9]+)?)\s+momentum\s+([0-9]+(?:\.[0-9]+)?)$",
        text,
    )
    if m:
        return f"스타일 가중치 rank {m.group(1)} / ai {m.group(2)} / momentum {m.group(3)}"

    return text


def _build_pipeline_diagnostics(
    analysis_targets: dict[str, Any],
    recommender_union_top10: dict[str, Any],
    analyzer_outputs_by_target: list[dict[str, Any]],
) -> dict[str, Any]:
    intersection_symbols = analysis_targets.get("intersection_symbols")
    top10_symbols = analysis_targets.get("top10_symbols")
    intersection_symbols = intersection_symbols if isinstance(intersection_symbols, list) else []
    top10_symbols = top10_symbols if isinstance(top10_symbols, list) else []

    target_groups_identical = bool(intersection_symbols) and set(intersection_symbols) == set(top10_symbols)

    top10_rows = recommender_union_top10.get("symbols")
    top10_rows = top10_rows if isinstance(top10_rows, list) else []
    empty_normalized_rows = 0
    empty_reason_rows = 0
    for row in top10_rows:
        if not isinstance(row, dict):
            continue
        if not row.get("normalized_by_skill"):
            empty_normalized_rows += 1
        if not row.get("reasons"):
            empty_reason_rows += 1

    uniform_score_items: list[dict[str, Any]] = []
    for output in analyzer_outputs_by_target:
        if not isinstance(output, dict):
            continue
        evaluations = output.get("evaluations")
        evaluations = evaluations if isinstance(evaluations, list) else []
        scores = [
            round(_to_float(row.get("score"), 0.0), 2)
            for row in evaluations
            if isinstance(row, dict) and row.get("score") is not None
        ]
        if len(scores) >= 2 and len(set(scores)) == 1:
            uniform_score_items.append(
                {
                    "skill_slug": str(output.get("skill_slug") or ""),
                    "target_group": str(output.get("target_group") or ""),
                    "score": scores[0],
                    "count": len(scores),
                }
            )

    messages: list[str] = []
    if target_groups_identical:
        messages.append("교집합 대상과 TOP10 대상이 동일해 두 표가 유사하게 보일 수 있습니다.")
    if empty_normalized_rows > 0:
        messages.append(f"TOP10 표에서 스킬별 정규화 점수가 비어 있는 행이 {empty_normalized_rows}개 있습니다.")
    if empty_reason_rows > 0:
        messages.append(f"TOP10 표에서 근거가 비어 있는 행이 {empty_reason_rows}개 있습니다.")
    for item in uniform_score_items:
        messages.append(
            f"{item['skill_slug']}({item['target_group']}) 점수가 {item['count']}종목 모두 {item['score']}로 동일합니다. (종목별 근거가 없는 거시/이벤트형 스킬에서 발생할 수 있음)"
        )

    return {
        "target_groups_identical": target_groups_identical,
        "empty_normalized_rows": empty_normalized_rows,
        "empty_reason_rows": empty_reason_rows,
        "uniform_score_items": uniform_score_items,
        "messages": messages,
    }


def _build_selected_skill_top5(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "ok":
            continue
        score = _to_float(item.get("score_0_100"), -1.0)
        if score < 0.0:
            continue
        confidence = _to_float(item.get("confidence_0_1"), 0.0)
        rows.append(
            {
                "skill_slug": str(item.get("skill_slug") or ""),
                "display_name": str(item.get("display_name") or str(item.get("skill_slug") or "")),
                "score_0_100": round(score, 2),
                "confidence_0_1": round(confidence, 2),
            }
        )
    rows.sort(key=lambda row: (-float(row.get("score_0_100", 0.0)), -float(row.get("confidence_0_1", 0.0)), str(row.get("skill_slug", ""))))
    return rows[:5]


def _build_final_intersection_top5(pipeline_tables: dict[str, Any]) -> list[dict[str, Any]]:
    final_summary = pipeline_tables.get("final_summary")
    if isinstance(final_summary, dict):
        top5 = final_summary.get("top5_from_top10")
        if isinstance(top5, list) and top5:
            rows: list[dict[str, Any]] = []
            for row in top5:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                if not symbol:
                    continue
                rows.append(
                    {
                        "symbol": symbol,
                        "final_score": round(_to_float(row.get("final_score"), 0.0), 2),
                        "support_count": _to_int(row.get("support_count"), 0),
                        "analyzer_avg_score": round(_to_float(row.get("analyzer_avg_score"), 0.0), 2),
                    }
                )
            if rows:
                return rows[:5]

    final_intersection = pipeline_tables.get("final_intersection")
    if not isinstance(final_intersection, dict):
        return []

    ranking = final_intersection.get("ranking")
    rows: list[dict[str, Any]] = []
    if isinstance(ranking, list):
        for row in ranking:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "final_score": round(_to_float(row.get("final_score"), 0.0), 2),
                    "support_count": _to_int(row.get("support_count"), 0),
                    "analyzer_avg_score": round(_to_float(row.get("analyzer_avg_score"), 0.0), 2),
                }
            )
    if rows:
        rows.sort(
            key=lambda row: (
                -float(row.get("final_score", 0.0)),
                -int(row.get("support_count", 0)),
                -float(row.get("analyzer_avg_score", 0.0)),
                str(row.get("symbol", "")),
            )
        )
        return rows[:5]


def _build_symbol_name_ko_map(
    top_picks: list[dict[str, Any]],
    pipeline_tables: dict[str, Any],
    results: list[dict[str, Any]],
    scope: str = "US",
    ai_symbols: list[str] | None = None,
) -> dict[str, str]:
    symbols: set[str] = set()
    inferred: dict[str, str] = {}
    inferred_company: dict[str, str] = {}
    universe_company_map = _load_universe_symbol_company_map(scope=scope)

    def _add_symbol(raw: Any) -> None:
        symbol = str(raw or "").strip().upper()
        if symbol:
            symbols.add(symbol)

    for pick in top_picks:
        if not isinstance(pick, dict):
            continue
        symbol = str(pick.get("symbol") or "").strip().upper()
        if symbol:
            symbols.add(symbol)
            company_name = str(pick.get("name") or "").strip()
            if company_name:
                inferred_company[symbol] = company_name
                ko = _company_alias_ko(company_name)
                if ko:
                    inferred[symbol] = ko

    for output in pipeline_tables.get("recommender_outputs", []):
        if not isinstance(output, dict):
            continue
        for row in output.get("symbols", []):
            if isinstance(row, dict):
                _add_symbol(row.get("symbol"))

    for symbol in pipeline_tables.get("recommender_intersection", {}).get("symbols", []):
        _add_symbol(symbol)

    for row in pipeline_tables.get("recommender_union_top10", {}).get("symbols", []):
        if isinstance(row, dict):
            _add_symbol(row.get("symbol"))

    for symbol in pipeline_tables.get("analysis_targets", {}).get("intersection_symbols", []):
        _add_symbol(symbol)
    for symbol in pipeline_tables.get("analysis_targets", {}).get("top10_symbols", []):
        _add_symbol(symbol)

    for output in pipeline_tables.get("analyzer_outputs_by_target", []):
        if not isinstance(output, dict):
            continue
        for row in output.get("evaluations", []):
            if isinstance(row, dict):
                _add_symbol(row.get("symbol"))

    for symbol in pipeline_tables.get("final_summary", {}).get("intersection_symbols", []):
        _add_symbol(symbol)
    for row in pipeline_tables.get("final_summary", {}).get("top5_from_top10", []):
        if isinstance(row, dict):
            _add_symbol(row.get("symbol"))

    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("skill_slug") or "") != "us-stock-analysis":
            continue
        payload = result.get("analysis_payload")
        if not isinstance(payload, dict):
            continue
        ticker = str(payload.get("ticker") or "").strip().upper()
        fundamentals = payload.get("fundamentals")
        if not ticker or not isinstance(fundamentals, dict):
            continue
        company = str(fundamentals.get("company") or "").strip()
        if company:
            inferred_company[ticker] = company
            ko = _company_alias_ko(company)
            if ko:
                inferred[ticker] = ko
            symbols.add(ticker)

    for symbol in ai_symbols or []:
        _add_symbol(symbol)

    # 화면에 노출되지 않은 심볼도 한글명 매핑을 미리 준비해 둔다.
    for symbol in universe_company_map:
        _add_symbol(symbol)

    symbol_name_ko: dict[str, str] = {}
    for symbol in sorted(symbols):
        company_name = inferred_company.get(symbol) or universe_company_map.get(symbol) or ""
        ko = (
            inferred.get(symbol)
            or KOREAN_SYMBOL_ALIASES.get(symbol)
            or _company_name_to_korean(company_name, symbol)
            or _ticker_to_korean(symbol)
        )
        if ko:
            symbol_name_ko[symbol] = ko
    return symbol_name_ko


def _company_alias_ko(company_name: str) -> str:
    direct = KOREAN_COMPANY_ALIASES.get(company_name)
    if direct:
        return direct
    normalized = _normalize_company_name(company_name)
    if not normalized:
        return ""
    return KOREAN_COMPANY_ALIASES.get(normalized, "")


def _company_name_to_korean(company_name: str, symbol: str) -> str:
    normalized = _normalize_company_name(company_name)
    if not normalized:
        return ""

    direct = KOREAN_COMPANY_ALIASES.get(normalized)
    if direct:
        return direct

    tokens = re.findall(r"[A-Za-z0-9&.+-]+", normalized)
    output_tokens: list[str] = []
    for token in tokens[:5]:
        upper = token.upper()
        if upper in COMPANY_NOISE_TOKENS:
            continue
        mapped = COMPANY_KO_TOKEN_ALIASES.get(upper)
        if mapped:
            output_tokens.append(mapped)
            continue
        if upper.isalpha() and len(upper) <= 5:
            output_tokens.append(_ticker_to_korean(upper))
            continue
        if upper.isdigit():
            output_tokens.append(upper)
            continue

    if output_tokens:
        if not any(token not in GENERIC_COMPANY_KO_TOKENS for token in output_tokens):
            return _ticker_to_korean(symbol)
        return " ".join(output_tokens[:3])
    return _ticker_to_korean(symbol)


def _ticker_to_korean(symbol: str) -> str:
    letters: list[str] = []
    for ch in str(symbol or "").upper():
        mapped = KOREAN_TICKER_LETTER_NAMES.get(ch)
        if mapped:
            letters.append(mapped)
    return "".join(letters)


def _normalize_company_name(company_name: str) -> str:
    text = str(company_name or "").strip()
    if not text:
        return ""
    for pattern in COMPANY_NAME_CLEANUP_PATTERNS:
        text = pattern.sub("", text).strip()
    text = re.sub(r"\s+", " ", text).strip(" -,.")
    return text


def _universe_cache_path(scope: str = "US") -> Path:
    normalized = str(scope or "US").strip().upper()
    if normalized == "KR":
        env_path = str(os.getenv("KR_UNIVERSE_CACHE_PATH") or "").strip()
        if env_path:
            return Path(env_path)
        return Path("reports/cache/universe/kr_universe.json")

    env_path = str(os.getenv("US_UNIVERSE_CACHE_PATH") or "").strip()
    if env_path:
        return Path(env_path)
    return Path("reports/cache/universe/us_universe.json")


def _load_universe_symbol_company_map(scope: str = "US") -> dict[str, str]:
    path = _universe_cache_path(scope=scope)
    if not path.exists():
        return {}
    try:
        stat = path.stat()
    except OSError:
        return {}
    return _load_universe_symbol_company_map_cached(str(path), int(stat.st_mtime_ns))


@lru_cache(maxsize=4)
def _load_universe_symbol_company_map_cached(path_str: str, _mtime_ns: int) -> dict[str, str]:
    path = Path(path_str)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        return {}
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        company = _normalize_company_name(str(row.get("name") or ""))
        if symbol and company:
            result[symbol] = company
    return result


def _build_ai_runtime(
    source_report: dict[str, Any],
    ai_report_service: AIReportService,
) -> dict[str, Any]:
    target_count = len(_extract_ai_target_symbols(source_report))
    api_configured = ai_report_service.api_configured()
    runtime = ai_report_service.read_runtime()
    status = str(runtime.get("status") or "idle").lower()
    is_running = status == "running"
    running_elapsed_sec: int | None = None
    running_delay_warn_sec = _coerce_int(
        os.getenv("AI_REPORT_RUNNING_DELAY_WARN_SEC"),
        default=300,
        min_value=60,
        max_value=3600,
    )
    if is_running:
        running_elapsed_sec = _runtime_elapsed_sec(runtime)
    disabled_reason = ""
    if is_running:
        disabled_reason = "AI 리포트 생성 진행 중"
    elif not api_configured:
        disabled_reason = "GLM API Key missing"
    elif target_count == 0:
        disabled_reason = "최종 TOP5 없음"

    latest_raw = ai_report_service.read_latest()
    latest_report = _normalize_ai_report(latest_raw) if isinstance(latest_raw, dict) else None

    return {
        "api_configured": api_configured,
        "status": status,
        "is_running": is_running,
        "running_elapsed_sec": running_elapsed_sec,
        "running_delay_warn_sec": running_delay_warn_sec,
        "is_running_delayed": bool(
            is_running and running_elapsed_sec is not None and running_elapsed_sec >= running_delay_warn_sec
        ),
        "runtime": runtime,
        "can_run": api_configured and target_count > 0 and not is_running,
        "disabled_reason": disabled_reason,
        "target_count": target_count,
        "latest_report": latest_report,
    }


def _extract_ai_target_symbols(source_report: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    pipeline = source_report.get("pipeline")
    if isinstance(pipeline, dict):
        final_summary = pipeline.get("final_summary")
        top5 = final_summary.get("top5_from_top10") if isinstance(final_summary, dict) else None
        if isinstance(top5, list):
            for row in top5[:5]:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
    if symbols:
        return symbols

    top_picks = source_report.get("top_picks")
    if isinstance(top_picks, list):
        for row in top_picks[:5]:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols[:5]


def _runtime_elapsed_sec(runtime: dict[str, Any]) -> int | None:
    started_raw = str(runtime.get("started_at") or runtime.get("updated_at") or "").strip()
    if not started_raw:
        return None
    parsed = _parse_iso_datetime(started_raw)
    if parsed is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0, int((now - parsed).total_seconds()))


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_int(raw: str | None, default: int, min_value: int, max_value: int) -> int:
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


@lru_cache(maxsize=1)
def _load_skill_detail_reference_map() -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(SKILL_DETAIL_REFERENCE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for raw_slug, raw_data in payload.items():
        slug = str(raw_slug or "").strip()
        if not slug or not isinstance(raw_data, dict):
            continue
        normalized[slug] = {
            "overview": str(raw_data.get("overview") or ""),
            "when_to_use": str(raw_data.get("when_to_use") or ""),
            "data_sources": str(raw_data.get("data_sources") or ""),
            "workflow": str(raw_data.get("workflow") or ""),
            "output": str(raw_data.get("output") or ""),
            "prerequisites": str(raw_data.get("prerequisites") or ""),
            "source": str(raw_data.get("source") or ""),
            "source_url": str(raw_data.get("source_url") or ""),
        }
    return normalized


def _family_label_ko(family: str) -> str:
    return {
        "market_analysis": "시장 분석",
        "calendar": "캘린더",
        "strategy_risk": "전략/리스크",
        "market_timing": "타이밍",
        "earnings_momentum": "실적 모멘텀",
        "screening": "스크리닝",
        "quality_orchestration": "품질 오케스트레이션",
        "edge_research": "엣지 리서치",
    }.get(str(family or ""), str(family or "-"))


def _role_label_ko(role: str) -> str:
    return {
        "direct": "직접 추천",
        "candidate": "추천 후보",
        "analysis_only": "분석 전용",
    }.get(str(role or ""), "분석 전용")


def _bool_label_ko(value: bool) -> str:
    return "예" if value else "아니오"


def _api_required_label_ko(value: bool) -> str:
    return "필요" if value else "불필요"


def _normalize_ai_report(raw: dict[str, Any]) -> dict[str, Any]:
    symbols_raw = raw.get("symbols")
    symbols_raw = symbols_raw if isinstance(symbols_raw, list) else []
    symbols: list[dict[str, Any]] = []
    for row in symbols_raw:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        decision = str(row.get("decision") or "WATCH").upper()
        decisions_ko = {
            "BUY": "매수",
            "WATCH": "관망",
            "AVOID": "비매수",
        }
        evidence_raw = row.get("evidence")
        evidence_raw = evidence_raw if isinstance(evidence_raw, list) else []
        evidence: list[dict[str, Any]] = []
        for item in evidence_raw:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip().lower()
            if source not in {"yahoo", "stooq", "fmp", "internal", "zai_search_mcp"}:
                continue
            evidence.append(
                {
                    "source": source,
                    "source_label": {
                        "yahoo": "Yahoo Finance",
                        "stooq": "Stooq",
                        "fmp": "FMP",
                        "internal": "내부 파이프라인",
                        "zai_search_mcp": "Z.ai Search MCP",
                    }.get(source, source),
                    "url": str(item.get("url") or ""),
                    "metrics": item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {},
                }
            )

        symbols.append(
            {
                "symbol": symbol,
                "decision": decision,
                "decision_ko": decisions_ko.get(decision, "관망"),
                "confidence_0_1": round(_to_float(row.get("confidence_0_1"), 0.5), 2),
                "score_0_100": round(_to_float(row.get("score_0_100"), 50.0), 2),
                "summary_ko": str(row.get("summary_ko") or ""),
                "reasons_ko": _to_str_list(row.get("reasons_ko")),
                "risks_ko": _to_str_list(row.get("risks_ko")),
                "evidence": evidence,
            }
        )

    return {
        "run_id": str(raw.get("run_id") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "status": str(raw.get("status") or "unavailable"),
        "provider": str(raw.get("provider") or "glm"),
        "model": str(raw.get("model") or "glm-4.5"),
        "portfolio_summary_ko": str(raw.get("portfolio_summary_ko") or ""),
        "warnings": _to_str_list(raw.get("warnings")),
        "symbols": symbols,
    }
