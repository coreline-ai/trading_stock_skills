from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean

from trading_skills_engine.core.models import SkillRunResult
from trading_skills_engine.data.provider import MarketDataProvider, MarketDataUnavailableError
from trading_skills_engine.engine.workflows import build_workflow_results
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills.evaluator import evaluate_skill


class SkillEngineOrchestrator:
    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        self.provider = provider or MarketDataProvider()

    def run_all_skills(self, selected_slugs: list[str] | None = None) -> dict:
        selected = self._select_skills(selected_slugs)
        market_state = None
        failure_reason = ""
        try:
            market_state, data_source = self.provider.load_market_state_with_source()
            results: list[SkillRunResult] = [evaluate_skill(skill, market_state) for skill in selected]
            workflows = build_workflow_results(results)
            market_state_dict = asdict(market_state)
            market_state_dict["as_of_date"] = market_state.as_of_date.isoformat()
        except MarketDataUnavailableError as exc:
            market_state_dict = {}
            data_source = "unavailable"
            results = []
            workflows = []
            failure_reason = str(exc)

        status_counts = {"growth": 0, "neutral": 0, "decline": 0}
        for item in results:
            status_counts[item.status] += 1

        if results and market_state_dict:
            top_candidates = self._aggregate_top_candidates(results)
            top_picks = self._build_top_picks(
                symbols=market_state.symbols if market_state else [],
                candidates=top_candidates,
            )
        else:
            top_picks = []

        report = {
            "app_name": "Coreline Stock AI",
            "as_of_date": market_state_dict.get("as_of_date", date.today().isoformat()),
            "generated_at": datetime.now(UTC).isoformat(),
            "data_source": data_source,
            "selected_skills": [item.slug for item in selected],
            "notification_count": max(0, status_counts["decline"] - 2),
            "auto_rebalance_enabled": True,
            "skill_count": len(results),
            "strategy_profiles": {
                "balanced": {"profitability": 0.36, "stability": 0.32, "growth": 0.32},
                "aggressive": {"profitability": 0.25, "stability": 0.15, "growth": 0.60},
                "defensive": {"profitability": 0.30, "stability": 0.55, "growth": 0.15},
            },
            "skill_classification_counts": status_counts,
            "market_state": market_state_dict,
            "skill_runs": [asdict(item) for item in results],
            "workflows": [asdict(item) for item in workflows],
            "top_picks": top_picks,
            "failure_reason": failure_reason,
            "quality_summary": {
                "avg_score": round(mean(item.score_0_100 for item in results), 2) if results else 0.0,
                "low_score_skills": [item.skill_slug for item in results if item.score_0_100 < 45],
            },
        }
        return report

    def write_report(self, output_path: Path, selected_slugs: list[str] | None = None) -> dict:
        report = self.run_all_skills(selected_slugs=selected_slugs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def _select_skills(selected_slugs: list[str] | None) -> list:
        if not selected_slugs:
            return SKILL_CATALOG
        wanted = {slug for slug in selected_slugs}
        selected = [skill for skill in SKILL_CATALOG if skill.slug in wanted]
        return selected if selected else SKILL_CATALOG

    @staticmethod
    def _aggregate_top_candidates(results: list[SkillRunResult]) -> list[str]:
        votes: dict[str, int] = {}
        for result in results:
            for rank, symbol in enumerate(result.top_candidates[:5], start=1):
                weight = 6 - rank  # 1st=5 ... 5th=1
                votes[symbol] = votes.get(symbol, 0) + weight
        ranked = sorted(votes.items(), key=lambda item: (item[1], item[0]), reverse=True)
        return [symbol for symbol, _ in ranked]

    @staticmethod
    def _build_top_picks(symbols: list, candidates: list[str]) -> list[dict]:
        by_symbol = {item.symbol: item for item in symbols}
        ordered_candidates = list(candidates)
        if len(ordered_candidates) < 5:
            fallback = sorted(
                symbols,
                key=lambda item: (item.ai_factor * 100 + item.momentum_20d + item.daily_return_pct),
                reverse=True,
            )
            for item in fallback:
                if item.symbol not in ordered_candidates:
                    ordered_candidates.append(item.symbol)
                if len(ordered_candidates) >= 5:
                    break

        picks: list[dict] = []
        for symbol in ordered_candidates[:5]:
            item = by_symbol.get(symbol)
            if not item:
                continue
            seed = 50 + item.momentum_20d
            sparkline = [max(5.0, min(95.0, seed + delta)) for delta in (-8, -4, -1, 3, 6, 8, 11)]
            picks.append(
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "return_pct": round(item.daily_return_pct, 2),
                    "ai_score_10": round(max(0.0, min(10.0, item.ai_factor * 10)), 1),
                    "sparkline_points": sparkline,
                }
            )
        return picks
