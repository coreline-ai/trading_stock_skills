from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.web.models import (
    DashboardHeader,
    DashboardViewModel,
    EngineHealth,
    FooterNavItem,
    MarketOverview,
    SkillCatalogItem,
    SkillResultRow,
    StrategyProfile,
    StrategyWeighting,
    TopPick,
    WorkflowCard,
)

DEFAULT_AVATAR_URL = (
    "https://images.unsplash.com/photo-1527980965255-d3b416303d12"
    "?auto=format&fit=crop&w=80&q=80"
)
DEFAULT_APP_NAME = "Coreline Stock AI"
DEFAULT_RISK_BADGES = ["투자 권유 아님", "무효화 레벨 확인"]
DEFAULT_SKILL_REPORT_PATH = Path("reports/skill_runs/latest_skill_runs.json")
DEFAULT_SNAPSHOT_PATH = Path("reports/eod/latest_snapshot.json")


@dataclass(frozen=True)
class ReportContext:
    payload: dict


class DashboardBFF:
    """Transforms engine outputs into dashboard DTOs."""

    def __init__(self, snapshot_path: Path | None = None) -> None:
        configured_skill_report = os.getenv("SKILL_RUN_REPORT_PATH")
        configured_snapshot = os.getenv("EOD_SNAPSHOT_PATH")
        self.force_snapshot_source = snapshot_path is not None and configured_skill_report is None

        self.skill_report_path = (
            Path(configured_skill_report) if configured_skill_report else DEFAULT_SKILL_REPORT_PATH
        )
        self.snapshot_path = (
            Path(configured_snapshot)
            if configured_snapshot
            else (snapshot_path or DEFAULT_SNAPSHOT_PATH)
        )

    def _load_report(self) -> ReportContext:
        payload: dict | None = None

        if self.force_snapshot_source and self.snapshot_path.exists():
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        elif self.skill_report_path.exists():
            payload = json.loads(self.skill_report_path.read_text(encoding="utf-8"))
        elif self.snapshot_path.exists():
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise FileNotFoundError(
                "No dashboard data found. Run `python scripts/run_full_engine.py` first."
            )

        return ReportContext(payload=payload)

    def get_header(self) -> DashboardHeader:
        context = self._load_report()
        as_of_raw = context.payload.get("as_of_date")
        return DashboardHeader(
            app_name=str(context.payload.get("app_name") or DEFAULT_APP_NAME),
            as_of_date=_iso_date_or_today(as_of_raw),
            notification_count=_safe_int(context.payload.get("notification_count"), default=0),
            user_avatar_url=str(context.payload.get("user_avatar_url") or DEFAULT_AVATAR_URL),
        )

    def get_strategy_weighting(self, profile: StrategyProfile) -> StrategyWeighting:
        context = self._load_report()
        profiles = context.payload.get("strategy_profiles") or {}
        config = profiles.get(profile.value) if isinstance(profiles, dict) else None

        if not isinstance(config, dict):
            config = _default_profile_weights(profile)

        profitability = _safe_float(config.get("profitability"), default=0.34)
        stability = _safe_float(config.get("stability"), default=0.33)
        growth = _safe_float(config.get("growth"), default=0.33)

        total = profitability + stability + growth
        if total <= 0:
            profitability, stability, growth = 0.34, 0.33, 0.33
            total = 1.0

        return StrategyWeighting(
            profile=profile,
            profitability=profitability / total,
            stability=stability / total,
            growth=growth / total,
            auto_rebalance_enabled=bool(context.payload.get("auto_rebalance_enabled", True)),
        )

    def get_market_overview(self) -> MarketOverview:
        context = self._load_report()
        counts = context.payload.get("skill_classification_counts") or {}
        if not isinstance(counts, dict):
            counts = {}

        return MarketOverview(
            decline_count=_safe_int(counts.get("decline"), default=0),
            neutral_count=_safe_int(counts.get("neutral"), default=0),
            growth_count=_safe_int(counts.get("growth"), default=0),
        )

    def get_top_picks(self, limit: int = 5) -> list[TopPick]:
        context = self._load_report()
        picks_payload = context.payload.get("top_picks") or []
        if not isinstance(picks_payload, list):
            picks_payload = []

        picks: list[TopPick] = []
        for raw in picks_payload:
            if not isinstance(raw, dict):
                continue

            return_pct = _safe_float(raw.get("return_pct"), default=0.0)
            ai_score_10 = _safe_float(raw.get("ai_score_10"), default=0.0)
            sparkline_points = _normalize_sparkline(raw.get("sparkline_points"), fallback_seed=return_pct)

            picks.append(
                TopPick(
                    symbol=str(raw.get("symbol") or "-"),
                    name=str(raw.get("name") or "Unknown"),
                    sector=str(raw.get("sector") or "Unknown"),
                    return_pct=return_pct,
                    ai_score_10=max(0.0, min(10.0, ai_score_10)),
                    sparkline_points=sparkline_points,
                )
            )

        picks.sort(key=lambda item: item.ai_score_10, reverse=True)
        return picks[: max(1, limit)]

    def get_workflows(self) -> list[WorkflowCard]:
        context = self._load_report()
        raw_workflows = context.payload.get("workflows") if isinstance(context.payload, dict) else None
        if not isinstance(raw_workflows, list):
            return []

        cards: list[WorkflowCard] = []
        for item in raw_workflows:
            if not isinstance(item, dict):
                continue
            cards.append(
                WorkflowCard(
                    workflow_name=str(item.get("workflow_name", "workflow")),
                    exposure_band=str(item.get("exposure_band", "-")),
                    portfolio_bias=str(item.get("portfolio_bias", "-")),
                    top_actions=[str(action) for action in item.get("top_actions", [])][:3],
                )
            )
        return cards

    def get_engine_health(self) -> EngineHealth:
        context = self._load_report()
        skill_count = _safe_int(context.payload.get("skill_count"), default=0)

        quality = context.payload.get("quality_summary") if isinstance(context.payload, dict) else {}
        if not isinstance(quality, dict):
            quality = {}

        avg_score = _safe_float(quality.get("avg_score"), default=0.0)
        low_skills = quality.get("low_score_skills") if isinstance(quality.get("low_score_skills"), list) else []
        return EngineHealth(
            skill_count=skill_count,
            avg_score=max(0.0, min(100.0, avg_score)),
            low_score_count=len(low_skills),
        )

    def get_selected_skills(self) -> list[str]:
        context = self._load_report()
        selected = context.payload.get("selected_skills")
        return [str(item) for item in selected] if isinstance(selected, list) else []

    def get_data_source(self) -> str:
        context = self._load_report()
        return str(context.payload.get("data_source") or "unavailable")

    def get_skill_catalog(self) -> list[SkillCatalogItem]:
        selected = set(self.get_selected_skills())
        if not selected:
            selected = {item.slug for item in SKILL_CATALOG}

        return [
            SkillCatalogItem(
                slug=item.slug,
                display_name=item.display_name,
                family=item.family,
                selected=item.slug in selected,
            )
            for item in SKILL_CATALOG
        ]

    def get_skill_results(self, limit: int = 20) -> list[SkillResultRow]:
        context = self._load_report()
        raw = context.payload.get("skill_runs")
        if not isinstance(raw, list):
            return []
        rows: list[SkillResultRow] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            rows.append(
                SkillResultRow(
                    skill_slug=str(item.get("skill_slug", "-")),
                    status=str(item.get("status", "neutral")),
                    score_0_100=_safe_float(item.get("score_0_100"), default=0.0),
                    confidence_0_1=max(0.0, min(1.0, _safe_float(item.get("confidence_0_1"), default=0.0))),
                    narrative_ko=str(item.get("narrative_ko", "")),
                )
            )
        rows.sort(key=lambda row: row.score_0_100, reverse=True)
        return rows[: max(1, limit)]

    @staticmethod
    def get_footer_nav() -> list[FooterNavItem]:
        return [
            FooterNavItem(id="home", label="Home", icon="dashboard", active=True),
            FooterNavItem(id="analysis", label="Analysis", icon="query_stats", active=False),
            FooterNavItem(id="watchlist", label="Watchlist", icon="favorite_border", active=False),
            FooterNavItem(id="settings", label="Settings", icon="settings", active=False),
        ]

    def get_dashboard_view_model(
        self,
        profile: StrategyProfile = StrategyProfile.BALANCED,
        limit: int = 5,
    ) -> DashboardViewModel:
        header = self.get_header()
        return DashboardViewModel(
            header=header,
            data_source=self.get_data_source(),
            selected_skills=self.get_selected_skills(),
            skill_catalog=self.get_skill_catalog(),
            skill_results=self.get_skill_results(limit=50),
            strategy_weighting=self.get_strategy_weighting(profile),
            market_overview=self.get_market_overview(),
            top_picks=self.get_top_picks(limit=limit),
            workflows=self.get_workflows(),
            engine_health=self.get_engine_health(),
            footer_nav=self.get_footer_nav(),
            risk_badges=DEFAULT_RISK_BADGES,
            date_display_ko=format_ko_date(header.as_of_date),
        )


def format_ko_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return "-"
    return parsed.strftime("%Y. %m. %d.")


def sparkline_to_svg_points(points: list[float]) -> str:
    if not points:
        return "0,20 100,20"

    clamped = [max(0.0, min(100.0, float(point))) for point in points]
    step = 100 / max(1, len(clamped) - 1)
    coords = [f"{index * step:.2f},{(40 - (value * 0.35)):.2f}" for index, value in enumerate(clamped)]
    return " ".join(coords)


def _iso_date_or_today(raw_value: object) -> str:
    if isinstance(raw_value, str):
        try:
            date.fromisoformat(raw_value)
            return raw_value
        except ValueError:
            pass
    return date.today().isoformat()


def _normalize_sparkline(raw_points: object, fallback_seed: float) -> list[float]:
    if isinstance(raw_points, list):
        normalized: list[float] = []
        for value in raw_points:
            number = _safe_float(value, default=math.nan)
            if math.isnan(number):
                continue
            normalized.append(max(0.0, min(100.0, number)))
        if len(normalized) >= 2:
            return normalized[:30]

    baseline = 50.0 + max(-15.0, min(15.0, fallback_seed))
    return [baseline - 8, baseline - 4, baseline - 6, baseline, baseline + 2, baseline + 6, baseline + 8]


def _default_profile_weights(profile: StrategyProfile) -> dict[str, float]:
    if profile == StrategyProfile.AGGRESSIVE:
        return {"profitability": 0.25, "stability": 0.15, "growth": 0.60}
    if profile == StrategyProfile.DEFENSIVE:
        return {"profitability": 0.30, "stability": 0.55, "growth": 0.15}
    return {"profitability": 0.36, "stability": 0.32, "growth": 0.32}


def _safe_int(value: object, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
