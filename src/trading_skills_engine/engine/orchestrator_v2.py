from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.data.fmp_calendar_client import FMPCalendarClient
from trading_skills_engine.data.fmp_news_client import FMPNewsClient
from trading_skills_engine.data.provider import MarketDataProvider
from trading_skills_engine.data.rss_client import RSSClient
from trading_skills_engine.skills_v2.base import AnalyzerContext, not_implemented_result, unavailable_result
from trading_skills_engine.skills_v2.contracts import (
    EngineRunRequestV2,
    EngineRunResponseV2,
    SkillRunResultV2,
    TopPickV2,
)
from trading_skills_engine.skills_v2.registry import all_skill_slugs, get_analyzer


class SkillEngineOrchestratorV2:
    def __init__(self, report_path: Path | None = None) -> None:
        env_report_path = os.getenv("SKILL_RUN_REPORT_V2_PATH")
        self.report_path = report_path or (Path(env_report_path) if env_report_path else Path("reports/skill_runs/latest_skill_runs_v2.json"))
        self.cache_store = CacheStore(Path("reports/cache/v2"))
        self.market_provider = MarketDataProvider()
        self.fmp_calendar = FMPCalendarClient.from_env()
        self.fmp_news = FMPNewsClient.from_env()
        self.rss_client = RSSClient()

    def run(self, request: EngineRunRequestV2) -> EngineRunResponseV2:
        selected = request.selected_skills or all_skill_slugs()
        as_of = request.as_of_date or date.today()

        context = AnalyzerContext(
            as_of_date=as_of,
            cache_store=self.cache_store,
            market_provider=self.market_provider,
            fmp_calendar=self.fmp_calendar,
            fmp_news=self.fmp_news,
            rss_client=self.rss_client,
            warnings=[],
        )

        results: list[SkillRunResultV2] = []
        for slug in selected:
            analyzer = get_analyzer(slug)
            if analyzer is None:
                if slug in all_skill_slugs():
                    results.append(not_implemented_result(slug))
                else:
                    results.append(
                        unavailable_result(
                            skill_slug=slug,
                            summary_ko="알 수 없는 스킬 slug입니다.",
                            reason_code="INVALID_SKILL",
                        )
                    )
                continue

            params = request.params_by_skill.get(slug, {}) if request.params_by_skill else {}
            try:
                result = analyzer.run(params=params, context=context)
            except Exception:
                result = unavailable_result(
                    skill_slug=slug,
                    summary_ko="스킬 실행 중 예외가 발생했습니다.",
                    reason_code="INTERNAL_ANALYZER_ERROR",
                )
            results.append(result)

        response = EngineRunResponseV2(
            as_of_date=as_of.isoformat(),
            data_sources=self._merge_data_sources(results),
            results=results,
            top_picks=self._build_top_picks(results),
            warnings=context.warnings,
        )
        return response

    def run_and_persist(self, request: EngineRunRequestV2) -> EngineRunResponseV2:
        response = self.run(request)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(response.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
        return response

    def read_latest(self) -> dict[str, Any] | None:
        if not self.report_path.exists():
            return None
        try:
            return json.loads(self.report_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _merge_data_sources(results: list[SkillRunResultV2]) -> dict[str, str]:
        merged = {"fmp": "unavailable", "rss": "unavailable"}
        for result in results:
            for source, state in result.source_statuses.items():
                current = merged.get(source, "unavailable")
                merged[source] = _max_state(current, state)
        return merged

    @staticmethod
    def _build_top_picks(results: list[SkillRunResultV2]) -> list[TopPickV2]:
        scores: dict[str, float] = {}

        for result in results:
            if result.status != "ok":
                continue

            if result.skill_slug == "us-stock-analysis":
                ticker = str(result.analysis_payload.get("ticker") or "").upper()
                if ticker:
                    scores[ticker] = scores.get(ticker, 0.0) + float(result.score_0_100 or 0)

            if result.skill_slug == "earnings-calendar":
                for row in result.analysis_payload.get("earnings", [])[:20]:
                    ticker = str(row.get("ticker") or "").upper()
                    market_cap = float(row.get("market_cap") or 0.0)
                    if ticker:
                        scores[ticker] = scores.get(ticker, 0.0) + min(20.0, market_cap / 200_000_000_000)

            if result.skill_slug == "market-news-analyst":
                for row in result.analysis_payload.get("ranked_events", [])[:20]:
                    impact = float(row.get("impact_score") or 0.0)
                    for ticker in row.get("related_tickers", [])[:2]:
                        symbol = str(ticker).upper()
                        if symbol:
                            scores[symbol] = scores.get(symbol, 0.0) + min(15.0, impact * 2)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
        return [TopPickV2(symbol=symbol, reason="v2 skill consensus", score=round(score, 2)) for symbol, score in ranked]


def _max_state(current: str, incoming: str) -> str:
    order = {"unavailable": 0, "stale": 1, "live": 2}
    return incoming if order.get(incoming, 0) > order.get(current, 0) else current
