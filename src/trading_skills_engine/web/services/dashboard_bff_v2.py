from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.registry import is_implemented

DEFAULT_REPORT_PATH = Path("reports/skill_runs/latest_skill_runs_v2.json")
DEFAULT_APP_NAME = "Coreline Stock AI"

DEFAULT_PARAMS_BY_SKILL: dict[str, dict[str, Any]] = {
    "economic-calendar-fetcher": {"from_days": 7, "to_days": 90, "country": "US"},
    "earnings-calendar": {"days": 7, "min_market_cap": 2_000_000_000},
    "market-news-analyst": {"lookback_days": 10, "max_items": 80},
    "us-stock-analysis": {"ticker": ""},
}


class DashboardBFFV2:
    def __init__(self, report_path: Path | None = None) -> None:
        env_path = os.getenv("SKILL_RUN_REPORT_V2_PATH")
        self.report_path = Path(env_path) if env_path else (report_path or DEFAULT_REPORT_PATH)

    def get_dashboard_view_model(self) -> dict[str, Any]:
        report = self._load_report()
        results = report["results"]
        selected_slugs = {str(item.get("skill_slug")) for item in results if isinstance(item, dict)}

        catalog = [
            {
                "slug": item.slug,
                "display_name": item.display_name,
                "family": item.family,
                "implemented": is_implemented(item.slug),
                "selected": item.slug in selected_slugs,
            }
            for item in SKILL_CATALOG
        ]
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

        return {
            "header": {
                "app_name": DEFAULT_APP_NAME,
                "as_of_date": report["as_of_date"],
            },
            "date_display_ko": _format_ko_date(report["as_of_date"]),
            "data_sources": report.get("data_sources", {"fmp": "unavailable", "rss": "unavailable"}),
            "warnings": report.get("warnings", []),
            "skill_catalog": catalog,
            "results": results_enriched,
            "top_picks": _normalize_top_picks(report.get("top_picks", [])),
            "risk_badges": ["투자 권유 아님", "무효화 레벨 확인"],
            "result_counts": {
                "ok": sum(1 for item in results_enriched if item.get("status") == "ok"),
                "unavailable": sum(1 for item in results_enriched if item.get("status") == "unavailable"),
                "not_implemented": sum(1 for item in results_enriched if item.get("status") == "not_implemented"),
            },
            "params_defaults": DEFAULT_PARAMS_BY_SKILL,
            "selected_skill_count": len(selected_slugs),
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

        return {
            "as_of_date": _parse_iso_date(str(payload.get("as_of_date") or date.today().isoformat())),
            "data_sources": payload.get("data_sources", {"fmp": "unavailable", "rss": "unavailable"}),
            "warnings": payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else [],
            "results": results if isinstance(results, list) else [],
            "top_picks": top_picks if isinstance(top_picks, list) else [],
        }


def _empty_report() -> dict[str, Any]:
    return {
        "as_of_date": date.today().isoformat(),
        "data_sources": {"fmp": "unavailable", "rss": "unavailable"},
        "warnings": ["아직 v2 실행 결과가 없습니다. 왼쪽에서 스킬을 선택하고 실행하세요."],
        "results": [],
        "top_picks": [],
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
            }
        )
    return normalized[:5]


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
