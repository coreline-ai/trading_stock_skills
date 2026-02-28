from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from trading_skills_engine.config.fmp_runtime import get_fmp_runtime_state
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.registry import is_implemented, is_recommendation_capable
from trading_skills_engine.skills_v2.traits import get_skill_trait

DEFAULT_REPORT_PATH = Path("reports/skill_runs/latest_skill_runs_v2.json")
DEFAULT_APP_NAME = "Coreline Stock AI"

DEFAULT_PARAMS_BY_SKILL: dict[str, dict[str, Any]] = {
    "economic-calendar-fetcher": {"from_days": 7, "to_days": 90, "country": "US"},
    "earnings-calendar": {"days": 7, "min_market_cap": 2_000_000_000},
    "market-news-analyst": {"lookback_days": 10, "max_items": 80},
    "us-stock-analysis": {"ticker": ""},
    "top-picks": {
        "mode": "skill_consensus",
        "watchlist": "NVDA, AVGO, AAPL, MSFT, AMZN",
        "limit": 5,
        "primary_skill": "us-stock-analysis",
        "confirm_skills": "earnings-calendar, market-news-analyst",
        "analysis_skills": "macro-regime-detector, market-environment-analysis",
        "min_confirm_votes": 1,
        "recommender_skills": "us-stock-analysis, market-news-analyst",
        "analyzer_skills": "macro-regime-detector",
        "recommender_top_n": 25,
        "include_watch": False,
        "comparison_mode": False,
    },
}
DEFAULT_SKILL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "core_reco",
        "label": "추천 코어 5",
        "description": "추천 생성에 직접 기여하는 핵심 조합",
        "slugs": [
            "us-stock-analysis",
            "earnings-calendar",
            "market-news-analyst",
            "market-breadth-analyzer",
            "uptrend-analyzer",
        ],
    },
    {
        "id": "momentum_swing",
        "label": "모멘텀 스윙",
        "description": "상승 추세/타이밍/실적 모멘텀 중심",
        "slugs": [
            "uptrend-analyzer",
            "market-top-detector",
            "ftd-detector",
            "earnings-trade-analyzer",
            "vcp-screener",
            "canslim-screener",
        ],
    },
    {
        "id": "defensive_blend",
        "label": "방어 밸런스",
        "description": "리스크/배당/방어 섹터 혼합",
        "slugs": [
            "portfolio-manager",
            "market-environment-analysis",
            "value-dividend-screener",
            "dividend-growth-pullback-screener",
            "economic-calendar-fetcher",
        ],
    },
]


class DashboardBFFV2:
    def __init__(self, report_path: Path | None = None) -> None:
        env_path = os.getenv("SKILL_RUN_REPORT_V2_PATH")
        self.report_path = Path(env_path) if env_path else (report_path or DEFAULT_REPORT_PATH)

    def get_dashboard_view_model(self) -> dict[str, Any]:
        report = self._load_report()
        results = report["results"]
        selected_slugs = {str(item.get("skill_slug")) for item in results if isinstance(item, dict)}
        raw_pipeline = report.get("pipeline", {})
        inferred_mode = _infer_top_picks_mode(report.get("top_picks", []), raw_pipeline)
        params_defaults = _params_defaults_with_mode(inferred_mode, raw_pipeline)

        catalog: list[dict[str, Any]] = []
        for item in SKILL_CATALOG:
            trait = get_skill_trait(item.slug)
            catalog.append(
                {
                    "slug": item.slug,
                    "display_name": item.display_name,
                    "family": item.family,
                    "implemented": is_implemented(item.slug),
                    "recommendation_capable": is_recommendation_capable(item.slug, mode=inferred_mode),
                    "trait_role": trait.recommendation_role if trait else "analysis_only",
                    "trait_style": trait.style if trait else item.family,
                    "trait_axes": list((trait.axis_weights or {}).keys()) if trait else [],
                    "selected": item.slug in selected_slugs,
                }
            )
        catalog_by_slug = {item["slug"]: item for item in catalog}

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
        selected_skill_top5 = _build_selected_skill_top5(results_enriched)
        final_intersection_top5 = _build_final_intersection_top5(pipeline_tables)

        return {
            "header": {
                "app_name": DEFAULT_APP_NAME,
                "as_of_date": report["as_of_date"],
            },
            "date_display_ko": _format_ko_date(report["as_of_date"]),
            "fmp_runtime": get_fmp_runtime_state(),
            "data_sources": report.get("data_sources", {"fmp": "unavailable", "rss": "unavailable"}),
            "warnings": report.get("warnings", []),
            "skill_catalog": catalog,
            "results": results_enriched,
            "top_picks": top_picks,
            "pipeline_tables": pipeline_tables,
            "summary_top5": {
                "selected_skill_scores": selected_skill_top5,
                "final_intersection": final_intersection_top5,
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
            "skill_presets": DEFAULT_SKILL_PRESETS,
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
            "warnings": payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else [],
            "results": results if isinstance(results, list) else [],
            "top_picks": top_picks if isinstance(top_picks, list) else [],
            "pipeline": pipeline if isinstance(pipeline, dict) else {},
        }


def _empty_report() -> dict[str, Any]:
    return {
        "as_of_date": date.today().isoformat(),
        "data_sources": {"fmp": "unavailable", "rss": "unavailable"},
        "warnings": ["아직 v2 실행 결과가 없습니다. 왼쪽에서 스킬을 선택하고 실행하세요."],
        "results": [],
        "top_picks": [],
        "pipeline": {},
    }


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
    top_picks["mode"] = mode if mode in {"skill_consensus", "watchlist_consensus", "role_gated_consensus", "two_stage_intersection"} else "skill_consensus"
    if isinstance(pipeline, dict):
        recommender_outputs = pipeline.get("recommender_outputs")
        if isinstance(recommender_outputs, list) and recommender_outputs:
            top_picks["recommender_skills"] = ", ".join(
                str(item.get("skill_slug") or "").strip()
                for item in recommender_outputs
                if isinstance(item, dict) and str(item.get("skill_slug") or "").strip()
            )
        analyzer_outputs_by_target = pipeline.get("analyzer_outputs_by_target")
        if isinstance(analyzer_outputs_by_target, list) and analyzer_outputs_by_target:
            analyzers: list[str] = []
            for item in analyzer_outputs_by_target:
                if not isinstance(item, dict):
                    continue
                if str(item.get("target_group") or "") != "top10":
                    continue
                slug = str(item.get("skill_slug") or "").strip()
                if slug and slug not in analyzers:
                    analyzers.append(slug)
            if analyzers:
                top_picks["analyzer_skills"] = ", ".join(analyzers)
        final_intersection = pipeline.get("final_intersection")
        if isinstance(final_intersection, dict):
            policy = str(final_intersection.get("policy_used") or "all_pass").strip().lower()
            top_picks["include_watch"] = policy == "pass_or_watch"
            comparison = final_intersection.get("comparison")
            top_picks["comparison_mode"] = bool(comparison.get("enabled")) if isinstance(comparison, dict) else False
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
    analyzer_outputs_by_target = raw_pipeline.get("analyzer_outputs_by_target")
    analyzer_outputs_by_target = analyzer_outputs_by_target if isinstance(analyzer_outputs_by_target, list) else []
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
    return {
        "recommender_outputs": recommender_outputs,
        "recommender_intersection": recommender_intersection,
        "recommender_union_top10": recommender_union_top10,
        "analysis_targets": analysis_targets,
        "analyzer_outputs": analyzer_outputs,
        "analyzer_outputs_by_target": analyzer_outputs_by_target,
        "final_intersection": final_intersection,
        "final_summary": final_summary,
        "counts": {
            "recommender_skills": len(recommender_outputs),
            "recommender_intersection": len(symbols) if isinstance(symbols, list) else 0,
            "analyzer_skills": len(analyzer_outputs),
            "final_symbols": len(final_symbols) if isinstance(final_symbols, list) else 0,
            "recommender_top10": len(top10_symbols) if isinstance(top10_symbols, list) else 0,
            "final_top5": len(top5_rows) if isinstance(top5_rows, list) else 0,
        },
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
        rows.sort(key=lambda row: (-float(row.get("final_score", 0.0)), -int(row.get("support_count", 0)), -float(row.get("analyzer_avg_score", 0.0)), str(row.get("symbol", ""))))
        return rows[:5]

    symbols = final_intersection.get("symbols")
    if isinstance(symbols, list):
        fallback: list[dict[str, Any]] = []
        for symbol in symbols[:5]:
            parsed = str(symbol or "").upper().strip()
            if not parsed:
                continue
            fallback.append(
                {
                    "symbol": parsed,
                    "final_score": 0.0,
                    "support_count": 0,
                    "analyzer_avg_score": 0.0,
                }
            )
        return fallback
    return []
