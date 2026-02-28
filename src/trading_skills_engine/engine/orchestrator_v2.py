from __future__ import annotations

import json
import os
import re
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
    AnalysisTargetsV2,
    AnalyzerEvaluationV2,
    AnalyzerOutputV2,
    AnalyzerOutputByTargetV2,
    EngineRunRequestV2,
    EngineRunResponseV2,
    FinalIntersectionV2,
    FinalSummaryV2,
    PipelineConfigV2,
    PipelineResultV2,
    RecommenderUnionTop10V2,
    RecommenderIntersectionV2,
    RecommenderOutputV2,
    RecommenderSymbolV2,
    SkillRunResultV2,
    TopPickV2,
)
from trading_skills_engine.skills_v2.registry import all_skill_slugs, get_analyzer
from trading_skills_engine.skills_v2.traits import get_skill_trait


INVALID_SYMBOL_TOKENS = {
    "NONE",
    "NYSE",
    "NASDAQ",
    "FOMC",
    "ECB",
    "FED",
    "CPI",
    "PPI",
    "NFP",
    "GDP",
    "USD",
    "EUR",
    "JPY",
    "GBP",
    "US",
    "LP",
    "PLC",
}


class SkillEngineOrchestratorV2:
    def __init__(self, report_path: Path | None = None) -> None:
        env_report_path = os.getenv("SKILL_RUN_REPORT_V2_PATH")
        self.report_path = report_path or (Path(env_report_path) if env_report_path else Path("reports/skill_runs/latest_skill_runs_v2.json"))
        self.history_dir = self.report_path.parent / "history_v2"
        self.cache_store = CacheStore(Path("reports/cache/v2"))
        self.market_provider = MarketDataProvider()
        self.fmp_calendar = FMPCalendarClient.from_env()
        self.fmp_news = FMPNewsClient.from_env()
        self.rss_client = RSSClient()

    def run(self, request: EngineRunRequestV2) -> EngineRunResponseV2:
        selected = _sanitize_selected_skills(request.selected_skills)
        if not selected:
            selected = all_skill_slugs()
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

        sanitized_watchlist = _sanitize_watchlist(request.watchlist_symbols)
        sanitized_limit = _sanitize_top_picks_limit(request.top_picks_limit)
        top_picks_params = request.params_by_skill.get("top-picks", {}) if request.params_by_skill else {}

        pipeline: PipelineResultV2 | None = None
        if request.top_picks_mode == "two_stage_intersection":
            pipeline, top_picks = self._build_two_stage_pipeline(
                results=results,
                watchlist=sanitized_watchlist,
                limit=sanitized_limit,
                pipeline_config=request.pipeline_config,
                top_picks_params=top_picks_params,
                warnings=context.warnings,
            )
        else:
            top_picks = self._build_top_picks(
                results=results,
                mode=request.top_picks_mode,
                watchlist=sanitized_watchlist,
                limit=sanitized_limit,
                top_picks_params=top_picks_params,
            )

        response = EngineRunResponseV2(
            as_of_date=as_of.isoformat(),
            data_sources=self._merge_data_sources(results),
            results=results,
            top_picks=top_picks,
            pipeline=pipeline,
            warnings=context.warnings,
        )
        return response

    def run_and_persist(self, request: EngineRunRequestV2) -> EngineRunResponseV2:
        response = self.run(request)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(response.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
        self.history_dir.mkdir(parents=True, exist_ok=True)
        history_path = self.history_dir / f"{response.run_id}.json"
        history_path.write_text(response.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
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
    def _build_top_picks(
        results: list[SkillRunResultV2],
        mode: str = "skill_consensus",
        watchlist: list[str] | None = None,
        limit: int = 5,
        top_picks_params: dict[str, Any] | None = None,
    ) -> list[TopPickV2]:
        if mode == "two_stage_intersection":
            return []
        if mode == "role_gated_consensus":
            return SkillEngineOrchestratorV2._build_role_gated_top_picks(
                results=results,
                watchlist=watchlist or [],
                limit=limit,
                params=top_picks_params or {},
            )
        if mode == "watchlist_consensus" and watchlist:
            return SkillEngineOrchestratorV2._build_watchlist_top_picks(results, watchlist, limit)
        return SkillEngineOrchestratorV2._build_skill_consensus_top_picks(results, limit)

    @staticmethod
    def _build_skill_consensus_top_picks(results: list[SkillRunResultV2], limit: int) -> list[TopPickV2]:
        scores: dict[str, float] = {}

        for result in results:
            if result.status != "ok":
                continue
            trait = get_skill_trait(result.skill_slug)
            if trait is None:
                continue
            payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
            role = trait.recommendation_role
            if role == "analysis_only":
                continue
            score_weight = max(0.25, min(1.25, float(result.score_0_100 or 50.0) / 100.0))
            skill_weight = trait.consensus_weight * score_weight
            symbol_rank_weight = 1.0 if role == "direct" else 0.75

            if result.skill_slug == "us-stock-analysis":
                ticker = str(payload.get("ticker") or "").upper()
                if ticker:
                    scores[ticker] = scores.get(ticker, 0.0) + float(result.score_0_100 or 0) * skill_weight

            if result.skill_slug == "earnings-calendar":
                for row in payload.get("earnings", [])[:20]:
                    ticker = str(row.get("ticker") or "").upper()
                    market_cap = float(row.get("market_cap") or 0.0)
                    if ticker:
                        scores[ticker] = scores.get(ticker, 0.0) + min(20.0, market_cap / 200_000_000_000) * skill_weight

            if result.skill_slug == "market-news-analyst":
                for row in payload.get("ranked_events", [])[:20]:
                    impact = float(row.get("impact_score") or 0.0)
                    for ticker in row.get("related_tickers", [])[:2]:
                        symbol = str(ticker).upper()
                        if symbol:
                            scores[symbol] = scores.get(symbol, 0.0) + min(15.0, impact * 2) * skill_weight

            extracted = _extract_symbols_from_payload(payload)
            for idx, symbol in enumerate(extracted[:12]):
                scores[symbol] = (
                    scores.get(symbol, 0.0)
                    + max(0.3, 5.0 - (idx * 0.4)) * skill_weight * symbol_rank_weight
                )

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [TopPickV2(symbol=symbol, reason="v2 skill consensus", score=round(score, 2)) for symbol, score in ranked]

    @staticmethod
    def _build_watchlist_top_picks(results: list[SkillRunResultV2], watchlist: list[str], limit: int) -> list[TopPickV2]:
        order = {symbol: idx for idx, symbol in enumerate(watchlist)}
        scores: dict[str, float] = {symbol: 0.0 for symbol in watchlist}

        for result in results:
            if result.status != "ok":
                continue

            trait = get_skill_trait(result.skill_slug)
            if trait is None:
                continue
            payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
            base_score = float(result.score_0_100 or 0.0)
            role = trait.recommendation_role
            role_factor = {"direct": 1.0, "candidate": 0.8, "analysis_only": 0.35}.get(role, 0.35)
            skill_weight = trait.consensus_weight * max(0.25, min(1.25, base_score / 100.0))
            global_adjust = (base_score - 50.0) * 0.02 * role_factor * skill_weight
            for symbol in scores:
                scores[symbol] += global_adjust
            if role == "analysis_only":
                continue

            if result.skill_slug == "us-stock-analysis":
                ticker = str(payload.get("ticker") or "").upper()
                if ticker in scores:
                    scores[ticker] += base_score * 0.9 * skill_weight

            if result.skill_slug == "earnings-calendar":
                for row in payload.get("earnings", [])[:20]:
                    ticker = str(row.get("ticker") or "").upper()
                    if ticker not in scores:
                        continue
                    market_cap = float(row.get("market_cap") or 0.0)
                    scores[ticker] += min(20.0, market_cap / 200_000_000_000) * skill_weight

            if result.skill_slug == "market-news-analyst":
                for row in payload.get("ranked_events", [])[:20]:
                    impact = float(row.get("impact_score") or 0.0)
                    for ticker in row.get("related_tickers", [])[:2]:
                        symbol = str(ticker).upper()
                        if symbol in scores:
                            scores[symbol] += min(15.0, impact * 2) * skill_weight

            for idx, candidate in enumerate(payload.get("top_candidates", [])[:10]):
                if not isinstance(candidate, dict):
                    continue
                symbol = str(candidate.get("symbol") or "").upper()
                if symbol not in scores:
                    continue
                scores[symbol] += max(0.5, 6.0 - idx * 0.5) * skill_weight

            extracted = _extract_symbols_from_payload(payload)
            for idx, symbol in enumerate(extracted[:12]):
                if symbol not in scores:
                    continue
                scores[symbol] += max(0.4, 4.5 - (idx * 0.35)) * skill_weight

        ranked = sorted(scores.items(), key=lambda x: (-x[1], order.get(x[0], 9999)))[:limit]
        return [TopPickV2(symbol=symbol, reason="watchlist consensus", score=round(score, 2)) for symbol, score in ranked]

    @staticmethod
    def _build_role_gated_top_picks(
        results: list[SkillRunResultV2],
        watchlist: list[str],
        limit: int,
        params: dict[str, Any],
    ) -> list[TopPickV2]:
        ok_results = [item for item in results if item.status == "ok"]
        if not ok_results:
            return []

        by_slug = {item.skill_slug: item for item in ok_results}
        requested_primary = str(params.get("primary_skill") or "").strip()
        requested_confirm = _sanitize_slugs(params.get("confirm_skills"))
        requested_analysis = _sanitize_slugs(params.get("analysis_skills"))
        min_confirm_votes = _sanitize_min_confirm_votes(params.get("min_confirm_votes"))

        primary = SkillEngineOrchestratorV2._pick_primary_skill(by_slug, requested_primary)
        if primary is None:
            return SkillEngineOrchestratorV2._build_skill_consensus_top_picks(results, limit)

        primary_symbols = _extract_symbols_from_payload(
            primary.analysis_payload if isinstance(primary.analysis_payload, dict) else {}
        )
        candidate_symbols = watchlist[:] if watchlist else primary_symbols[:]
        if not candidate_symbols:
            candidate_symbols = [
                item.symbol for item in SkillEngineOrchestratorV2._build_skill_consensus_top_picks(results, max(5, limit))
            ]

        confirm_skills = SkillEngineOrchestratorV2._pick_confirm_skills(
            by_slug=by_slug,
            primary_slug=primary.skill_slug,
            requested=requested_confirm,
        )
        analysis_skills = SkillEngineOrchestratorV2._pick_analysis_skills(
            by_slug=by_slug,
            requested=requested_analysis,
        )

        primary_symbol_order = {symbol: idx for idx, symbol in enumerate(primary_symbols)}
        scored: list[dict[str, Any]] = []
        for symbol in candidate_symbols[:200]:
            if not symbol:
                continue
            symbol = symbol.upper()
            if not re.fullmatch(r"[A-Z0-9.\-]+", symbol):
                continue

            confirm_hit_skills: list[str] = []
            for slug in confirm_skills:
                payload = by_slug[slug].analysis_payload if isinstance(by_slug[slug].analysis_payload, dict) else {}
                confirm_symbols = _extract_symbols_from_payload(payload)
                if symbol in confirm_symbols:
                    confirm_hit_skills.append(slug)
            confirm_votes = len(confirm_hit_skills)

            veto_skill_hits: list[str] = []
            for slug in analysis_skills:
                analysis_result = by_slug[slug]
                if float(analysis_result.score_0_100 or 50.0) < 38.0 and float(analysis_result.confidence_0_1 or 0.5) >= 0.45:
                    veto_skill_hits.append(slug)
            veto_count = len(veto_skill_hits)

            rank = primary_symbol_order.get(symbol, 99)
            rank_bonus = max(0.0, 8.0 - rank * 0.8)
            base = float(primary.score_0_100 or 50.0) * 0.55 + rank_bonus
            score = base + (confirm_votes * 10.0) - (veto_count * 14.0)
            score = max(0.0, min(100.0, score))

            if veto_count > 0:
                decision = "REJECT"
            elif confirm_skills and confirm_votes >= min_confirm_votes:
                decision = "PASS"
            elif confirm_skills:
                decision = "WATCH"
            else:
                decision = "WATCH"

            reason = (
                f"role gated {decision} · primary {primary.skill_slug} · "
                f"confirm {confirm_votes}/{max(1, len(confirm_skills))} · veto {veto_count}"
            )
            scored.append(
                {
                    "symbol": symbol,
                    "reason": reason,
                    "score": score,
                    "decision": decision,
                    "primary_skill": primary.skill_slug,
                    "confirm_votes": confirm_votes,
                    "confirm_required": max(1, len(confirm_skills)),
                    "veto_count": veto_count,
                    "confirm_hits": confirm_hit_skills,
                    "veto_skills": veto_skill_hits,
                }
            )

        decision_priority = {"PASS": 0, "WATCH": 1, "REJECT": 2}

        def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
            decision = str(row.get("decision") or "WATCH")
            score = float(row.get("score") or 0.0)
            return (decision_priority.get(decision, 9), -score)

        ranked = sorted(scored, key=_sort_key)[:limit]
        return [
            TopPickV2(
                symbol=str(item["symbol"]),
                reason=str(item["reason"]),
                score=round(float(item["score"]), 2),
                decision=str(item["decision"]),
                primary_skill=str(item["primary_skill"]),
                confirm_votes=int(item["confirm_votes"]),
                confirm_required=int(item["confirm_required"]),
                veto_count=int(item["veto_count"]),
                confirm_hits=[str(v) for v in item.get("confirm_hits", [])],
                veto_skills=[str(v) for v in item.get("veto_skills", [])],
            )
            for item in ranked
        ]

    @staticmethod
    def _build_two_stage_pipeline(
        results: list[SkillRunResultV2],
        watchlist: list[str],
        limit: int,
        pipeline_config: PipelineConfigV2 | None,
        top_picks_params: dict[str, Any],
        warnings: list[str],
    ) -> tuple[PipelineResultV2, list[TopPickV2]]:
        ok_results = [item for item in results if item.status == "ok"]
        by_slug = {item.skill_slug: item for item in ok_results}

        raw_recommenders = (
            list(pipeline_config.recommender_skills)
            if pipeline_config and pipeline_config.recommender_skills
            else _sanitize_slugs(top_picks_params.get("recommender_skills"))
        )
        raw_analyzers = (
            list(pipeline_config.analyzer_skills)
            if pipeline_config and pipeline_config.analyzer_skills
            else _sanitize_slugs(top_picks_params.get("analyzer_skills"))
        )
        top_n = (
            int(pipeline_config.recommender_top_n)
            if pipeline_config is not None
            else _sanitize_recommender_top_n(top_picks_params.get("recommender_top_n"))
        )
        top_n = _sanitize_recommender_top_n(top_n)
        analyzer_pass_policy = _sanitize_analyzer_pass_policy(
            pipeline_config.analyzer_pass_policy
            if pipeline_config is not None
            else top_picks_params.get("analyzer_pass_policy")
        )
        comparison_mode = bool(
            pipeline_config.comparison_mode
            if pipeline_config is not None
            else _to_bool(top_picks_params.get("comparison_mode"), False)
        )
        fallback_to_watch_on_empty = _to_bool(top_picks_params.get("fallback_to_watch_on_empty"), False)

        if not raw_recommenders:
            raw_recommenders = [
                item.skill_slug
                for item in ok_results
                if (trait := get_skill_trait(item.skill_slug)) and trait.recommendation_role in {"direct", "candidate"}
            ]
        if not raw_analyzers:
            raw_analyzers = [
                item.skill_slug
                for item in ok_results
                if (trait := get_skill_trait(item.skill_slug)) and trait.recommendation_role == "analysis_only"
            ]

        recommender_skills: list[str] = []
        for slug in raw_recommenders:
            if slug not in by_slug:
                warnings.append(f"two-stage: recommender '{slug}' 실행 결과가 없어 제외되었습니다.")
                continue
            trait = get_skill_trait(slug)
            if trait is None or trait.recommendation_role not in {"direct", "candidate"}:
                warnings.append(f"two-stage: recommender '{slug}' role 불일치로 제외되었습니다.")
                continue
            if slug not in recommender_skills:
                recommender_skills.append(slug)
        if len(recommender_skills) > 5:
            warnings.append("two-stage: recommender 스킬은 최대 5개라 앞 5개만 사용했습니다.")
            recommender_skills = recommender_skills[:5]

        analyzer_skills: list[str] = []
        for slug in raw_analyzers:
            if slug not in by_slug:
                warnings.append(f"two-stage: analyzer '{slug}' 실행 결과가 없어 제외되었습니다.")
                continue
            trait = get_skill_trait(slug)
            if trait is None or trait.recommendation_role != "analysis_only":
                warnings.append(f"two-stage: analyzer '{slug}' role 불일치로 제외되었습니다.")
                continue
            if slug not in analyzer_skills:
                analyzer_skills.append(slug)
        if len(analyzer_skills) > 3:
            warnings.append("two-stage: analyzer 스킬은 최대 3개라 앞 3개만 사용했습니다.")
            analyzer_skills = analyzer_skills[:3]

        dropped_by_stage: list[str] = []
        recommender_outputs: list[RecommenderOutputV2] = []
        support_count_all: dict[str, int] = {}
        for slug in recommender_skills:
            ranked_rows = SkillEngineOrchestratorV2._extract_ranked_symbols_for_recommender(
                result=by_slug[slug],
                top_n=top_n,
            )
            if watchlist:
                watchset = set(watchlist)
                ranked_rows = [row for row in ranked_rows if row[0] in watchset]
            symbols = [
                RecommenderSymbolV2(
                    symbol=symbol,
                    rank=idx + 1,
                    percentile=round(_percentile(idx, len(ranked_rows)), 2),
                    raw_score=round(raw_score, 2),
                    reason=reason,
                )
                for idx, (symbol, raw_score, reason) in enumerate(ranked_rows)
            ]
            if not symbols:
                warnings.append(f"two-stage: recommender '{slug}'에서 종목 추출 실패")
            recommender_outputs.append(RecommenderOutputV2(skill_slug=slug, symbols=symbols))
            for row in symbols:
                support_count_all[row.symbol] = support_count_all.get(row.symbol, 0) + 1

        if not recommender_outputs:
            dropped_by_stage.append("recommender_outputs_empty")

        # Raw strict intersection across recommender outputs (before analyzer filtering)
        recommender_symbol_sets = [set(item.symbol for item in output.symbols) for output in recommender_outputs]
        if len(recommender_symbol_sets) >= 2:
            base_set = set(recommender_symbol_sets[0])
            for symbol_set in recommender_symbol_sets[1:]:
                base_set &= symbol_set
            recommender_intersection_symbols = sorted(base_set)
        elif len(recommender_symbol_sets) == 1:
            # Intersection is only meaningful when at least two recommenders are selected.
            recommender_intersection_symbols = []
        else:
            recommender_intersection_symbols = []

        if not recommender_intersection_symbols:
            dropped_by_stage.append("recommender_intersection_empty")
        symbol_union_map: dict[str, dict[str, Any]] = {}
        for output in recommender_outputs:
            for row in output.symbols:
                symbol_entry = symbol_union_map.setdefault(
                    row.symbol,
                    {
                        "symbol": row.symbol,
                        "normalized_by_skill": {},
                        "reasons": [],
                    },
                )
                symbol_entry["normalized_by_skill"][output.skill_slug] = float(row.percentile)
                symbol_entry["reasons"].append(f"{output.skill_slug}:{row.reason}")

        union_rows: list[dict[str, Any]] = []
        for symbol, row in symbol_union_map.items():
            normalized_by_skill = row.get("normalized_by_skill", {})
            support_count = len(normalized_by_skill)
            composite_score = float(sum(float(v) for v in normalized_by_skill.values()))
            union_rows.append(
                {
                    "symbol": symbol,
                    "support_count": support_count,
                    "composite_score": round(composite_score, 2),
                    "normalized_by_skill": normalized_by_skill,
                    "reasons": row.get("reasons", []),
                }
            )
        union_rows.sort(
            key=lambda row: (
                -int(row.get("support_count", 0)),
                -float(row.get("composite_score", 0.0)),
                str(row.get("symbol", "")),
            )
        )
        recommender_union_top10_rows = []
        for idx, row in enumerate(union_rows[:10]):
            recommender_union_top10_rows.append(
                {
                    "symbol": str(row["symbol"]),
                    "rank": idx + 1,
                    "composite_score": float(row["composite_score"]),
                    "support_count": int(row["support_count"]),
                    "normalized_by_skill": dict(row.get("normalized_by_skill", {})),
                    "reasons": list(row.get("reasons", [])),
                }
            )
        if not recommender_union_top10_rows:
            dropped_by_stage.append("recommender_union_top10_empty")

        target_symbols: dict[str, list[str]] = {
            "intersection": list(recommender_intersection_symbols),
            "top10": [str(item["symbol"]) for item in recommender_union_top10_rows],
        }

        analyzer_outputs: list[AnalyzerOutputV2] = []
        analyzer_outputs_by_target: list[AnalyzerOutputByTargetV2] = []
        analyzer_decisions_by_target_skill: dict[str, dict[str, dict[str, str]]] = {
            "intersection": {},
            "top10": {},
        }
        analyzer_scores_by_target_symbol: dict[str, dict[str, dict[str, float]]] = {
            "intersection": {},
            "top10": {},
        }
        analyzer_risks_by_symbol: dict[str, list[str]] = {}

        for slug in analyzer_skills:
            analysis_result = by_slug[slug]
            combined_evaluations: list[AnalyzerEvaluationV2] = []
            for target_group in ("intersection", "top10"):
                symbols = target_symbols[target_group]
                evaluations: list[AnalyzerEvaluationV2] = []
                decisions: dict[str, str] = {}
                for symbol in symbols:
                    row = SkillEngineOrchestratorV2._evaluate_symbol_for_analyzer(
                        symbol=symbol,
                        result=analysis_result,
                        target_group=target_group,
                    )
                    evaluations.append(row)
                    combined_evaluations.append(row)
                    decisions[symbol] = row.decision
                    analyzer_scores_by_target_symbol[target_group].setdefault(symbol, {})
                    analyzer_scores_by_target_symbol[target_group][symbol][slug] = float(row.score)
                    for risk in row.risk_flags:
                        analyzer_risks_by_symbol.setdefault(symbol, [])
                        if risk not in analyzer_risks_by_symbol[symbol]:
                            analyzer_risks_by_symbol[symbol].append(risk)

                analyzer_decisions_by_target_skill[target_group][slug] = decisions
                analyzer_outputs_by_target.append(
                    AnalyzerOutputByTargetV2(
                        skill_slug=slug,
                        target_group=target_group,
                        evaluations=evaluations,
                    )
                )

            analyzer_outputs.append(AnalyzerOutputV2(skill_slug=slug, evaluations=combined_evaluations))

        if not analyzer_outputs:
            warnings.append("two-stage: analyzer 스킬이 없어 최종 결과는 빈 결과입니다.")
            dropped_by_stage.append("analyzer_skills_empty")

        def _filter_target_symbols(target_group: str, policy: str) -> list[str]:
            symbols = target_symbols.get(target_group, [])
            if not symbols:
                return []
            if not analyzer_skills:
                return []
            accepted = {"PASS"} if policy == "all_pass" else {"PASS", "WATCH"}
            filtered = set(symbols)
            for analyzer_slug in analyzer_skills:
                decision_map = analyzer_decisions_by_target_skill.get(target_group, {}).get(analyzer_slug, {})
                accepted_symbols = {symbol for symbol in symbols if decision_map.get(symbol) in accepted}
                filtered &= accepted_symbols
            return sorted(filtered)

        strict_intersection_symbols = _filter_target_symbols("intersection", analyzer_pass_policy)
        strict_top10_symbols = _filter_target_symbols("top10", analyzer_pass_policy)
        final_intersection_symbols = list(strict_intersection_symbols)
        final_top10_symbols = list(strict_top10_symbols)
        effective_policy = analyzer_pass_policy

        if recommender_intersection_symbols and analyzer_skills and not strict_intersection_symbols:
            dropped_by_stage.append(f"analyzer_filtered_intersection_empty[{analyzer_pass_policy}]")
        if target_symbols["top10"] and analyzer_skills and not strict_top10_symbols:
            dropped_by_stage.append(f"analyzer_filtered_top10_empty[{analyzer_pass_policy}]")
            if (
                fallback_to_watch_on_empty
                and analyzer_pass_policy == "all_pass"
            ):
                watch_intersection_symbols = _filter_target_symbols("intersection", "pass_or_watch")
                watch_top10_symbols = _filter_target_symbols("top10", "pass_or_watch")
                if watch_top10_symbols:
                    final_intersection_symbols = watch_intersection_symbols
                    final_top10_symbols = watch_top10_symbols
                    effective_policy = "pass_or_watch"
                    warnings.append(
                        "two-stage: all_pass 결과가 비어 pass_or_watch 폴백을 적용했습니다."
                    )
                    dropped_by_stage.append("fallback_pass_or_watch_applied")

        def _build_rank_rows(symbols: list[str], target_group: str) -> list[dict[str, Any]]:
            volatility_proxy = SkillEngineOrchestratorV2._build_volatility_proxy(results)
            rows: list[dict[str, Any]] = []
            for symbol in symbols:
                support_count = support_count_all.get(symbol, 0)
                score_map = analyzer_scores_by_target_symbol.get(target_group, {}).get(symbol, {})
                analyzer_scores = list(score_map.values())
                analyzer_avg = sum(analyzer_scores) / len(analyzer_scores) if analyzer_scores else 0.0
                volatility = float(volatility_proxy.get(symbol, 35.0))
                final_score = support_count * 20.0 + analyzer_avg * 0.8 - volatility * 0.3
                rows.append(
                    {
                        "symbol": symbol,
                        "support_count": support_count,
                        "analyzer_avg_score": round(analyzer_avg, 2),
                        "volatility_proxy": round(volatility, 2),
                        "final_score": round(final_score, 2),
                    }
                )
            rows.sort(
                key=lambda row: (
                    -float(row.get("final_score", 0.0)),
                    -float(row.get("analyzer_avg_score", 0.0)),
                    -int(row.get("support_count", 0)),
                    float(row.get("volatility_proxy", 999.0)),
                    str(row.get("symbol", "")),
                )
            )
            return rows

        intersection_ranking_rows = _build_rank_rows(final_intersection_symbols, "intersection")
        top10_ranking_rows = _build_rank_rows(final_top10_symbols, "top10")
        top5_from_top10 = top10_ranking_rows[:5]

        comparison: dict[str, Any] = {}
        if comparison_mode:
            strict_intersection = _filter_target_symbols("intersection", "all_pass")
            strict_top10 = _filter_target_symbols("top10", "all_pass")
            watch_intersection = _filter_target_symbols("intersection", "pass_or_watch")
            watch_top10 = _filter_target_symbols("top10", "pass_or_watch")
            comparison = {
                "enabled": True,
                "strict_all_pass": {
                    "symbols": strict_top10,
                    "count": len(strict_top10),
                    "by_target": {
                        "intersection": strict_intersection,
                        "top10": strict_top10,
                    },
                },
                "watch_inclusive": {
                    "symbols": watch_top10,
                    "count": len(watch_top10),
                    "by_target": {
                        "intersection": watch_intersection,
                        "top10": watch_top10,
                    },
                },
                "watch_only_delta": sorted(set(watch_top10) - set(strict_top10)),
            }

        post_analyzer_by_recommender: list[dict[str, Any]] = []
        final_top10_set = set(final_top10_symbols)
        for output in recommender_outputs:
            filtered_symbols = [row.symbol for row in output.symbols if row.symbol in final_top10_set]
            post_analyzer_by_recommender.append(
                {
                    "recommender_skill": output.skill_slug,
                    "symbols": filtered_symbols,
                    "count": len(filtered_symbols),
                }
            )

        analyzer_policy_label = "all-pass" if effective_policy == "all_pass" else "pass-or-watch"
        top_picks = [
            TopPickV2(
                symbol=str(row["symbol"]),
                reason=(
                    "two-stage top10 analysis"
                    f" · support {int(row['support_count'])}/{max(1, len(recommender_outputs))}"
                    f" · analyzer {analyzer_policy_label} {len(analyzer_outputs)}/{max(1, len(analyzer_outputs))}"
                ),
                score=float(row["final_score"]),
                decision="PASS",
                primary_skill=(recommender_skills[0] if recommender_skills else None),
                confirm_votes=int(row["support_count"]),
                confirm_required=max(1, len(recommender_outputs)),
                veto_count=0,
                confirm_hits=[
                    output.skill_slug
                    for output in recommender_outputs
                    if row["symbol"] in {item.symbol for item in output.symbols}
                ],
                veto_skills=analyzer_risks_by_symbol.get(str(row["symbol"]), []),
            )
            for row in top5_from_top10[:limit]
        ]

        final_reasons = [
            f"recommender {len(recommender_outputs)}개 strict intersection {len(recommender_intersection_symbols)}개",
            f"recommender union normalized top10 {len(recommender_union_top10_rows)}개",
            f"analyzer {len(analyzer_outputs)}개 policy={effective_policy}",
            f"analysis filtered intersection {len(final_intersection_symbols)}개",
            f"analysis filtered top10 {len(final_top10_symbols)}개",
        ]
        for item in dropped_by_stage:
            final_reasons.append(f"drop: {item}")

        pipeline = PipelineResultV2(
            recommender_outputs=recommender_outputs,
            recommender_intersection=RecommenderIntersectionV2(
                symbols=recommender_intersection_symbols,
                support_count_by_symbol={symbol: support_count_all.get(symbol, 0) for symbol in recommender_intersection_symbols},
                dropped_by_stage=dropped_by_stage,
            ),
            recommender_union_top10=RecommenderUnionTop10V2(
                symbols=recommender_union_top10_rows,
                source_union_count=len(symbol_union_map),
            ),
            analysis_targets=AnalysisTargetsV2(
                intersection_symbols=list(recommender_intersection_symbols),
                top10_symbols=list(target_symbols["top10"]),
            ),
            analyzer_outputs=analyzer_outputs,
            analyzer_outputs_by_target=analyzer_outputs_by_target,
            final_intersection=FinalIntersectionV2(
                symbols=final_intersection_symbols,
                final_reasons=final_reasons,
                policy_used=effective_policy,
                comparison=comparison,
                post_analyzer_by_recommender=post_analyzer_by_recommender,
                per_skill_traces=[],
                ranking=intersection_ranking_rows,
            ),
            final_summary=FinalSummaryV2(
                intersection_symbols=final_intersection_symbols,
                top5_from_top10=top5_from_top10,
                policy_used=effective_policy,
                dropped_by_stage=dropped_by_stage,
            ),
        )
        return pipeline, top_picks

    @staticmethod
    def _extract_ranked_symbols_for_recommender(
        result: SkillRunResultV2,
        top_n: int,
    ) -> list[tuple[str, float, str]]:
        payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
        ranked: dict[str, tuple[float, str]] = {}

        def _put(raw_symbol: Any, raw_score: Any, reason: str) -> None:
            symbol = _sanitize_symbol(raw_symbol)
            if not symbol:
                return
            score = _to_float(raw_score, 0.0)
            current = ranked.get(symbol)
            if current is None or score > current[0]:
                ranked[symbol] = (score, reason)

        _put(payload.get("ticker"), result.score_0_100 or 55.0, "ticker")

        for idx, row in enumerate(payload.get("top_candidates", [])[: top_n * 3]):
            if not isinstance(row, dict):
                continue
            score = _to_float(
                row.get("composite_score"),
                _to_float(row.get("score"), max(0.0, 80.0 - idx)),
            )
            _put(row.get("symbol"), score, "top_candidates")

        for idx, row in enumerate(payload.get("earnings", [])[: top_n * 3]):
            if not isinstance(row, dict):
                continue
            market_cap = _to_float(row.get("market_cap"), 0.0)
            _put(row.get("ticker"), min(100.0, 35.0 + market_cap / 50_000_000_000), "earnings")

        for idx, row in enumerate(payload.get("ranked_events", [])[: top_n * 3]):
            if not isinstance(row, dict):
                continue
            impact = _to_float(row.get("impact_score"), 0.0)
            for related in row.get("related_tickers", [])[:3]:
                _put(related, min(100.0, 45.0 + impact * 12.0 - idx * 0.5), "ranked_events")

        for idx, symbol in enumerate(_extract_symbols_from_payload(payload)[: top_n * 3]):
            _put(symbol, max(0.0, 70.0 - idx), "payload_extract")

        sorted_rows = sorted(ranked.items(), key=lambda item: item[1][0], reverse=True)[:top_n]
        return [(symbol, score_reason[0], score_reason[1]) for symbol, score_reason in sorted_rows]

    @staticmethod
    def _apply_analyzer_policy(
        symbols_by_recommender: dict[str, list[str]],
        analyzer_skills: list[str],
        analyzer_decisions_by_skill: dict[str, dict[str, dict[str, str]]],
        analyzer_pass_policy: str,
        recommender_skills: list[str],
    ) -> tuple[dict[str, set[str]], list[str]]:
        accepted_decisions = {"PASS"} if analyzer_pass_policy == "all_pass" else {"PASS", "WATCH"}
        filtered_sets: dict[str, set[str]] = {}
        for recommender_slug, symbols in symbols_by_recommender.items():
            filtered = set(symbols)
            for analyzer_slug in analyzer_skills:
                decision_map = analyzer_decisions_by_skill.get(analyzer_slug, {}).get(recommender_slug, {})
                accepted_symbols = {
                    symbol for symbol in symbols if decision_map.get(symbol) in accepted_decisions
                }
                filtered &= accepted_symbols
            filtered_sets[recommender_slug] = filtered

        if len(recommender_skills) >= 2:
            intersection_set = set(filtered_sets.get(recommender_skills[0], set()))
            for slug in recommender_skills[1:]:
                intersection_set &= set(filtered_sets.get(slug, set()))
            final_symbols = sorted(intersection_set)
        elif len(recommender_skills) == 1:
            final_symbols = sorted(filtered_sets.get(recommender_skills[0], set()))
        else:
            final_symbols = []
        return filtered_sets, final_symbols

    @staticmethod
    def _evaluate_symbol_for_analyzer(
        symbol: str,
        result: SkillRunResultV2,
        source_recommender: str | None = None,
        target_group: str | None = None,
    ) -> AnalyzerEvaluationV2:
        payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
        matched_symbols = set(_extract_symbols_from_payload(payload))
        base_score = _to_float(result.score_0_100, 50.0)
        confidence = _to_float(result.confidence_0_1, 0.5)
        match_bonus = 14.0 if symbol in matched_symbols else -8.0
        score = base_score * 0.65 + confidence * 100.0 * 0.2 + match_bonus
        score = max(0.0, min(100.0, score))

        reasons: list[str] = [
            f"base {base_score:.1f}",
            f"confidence {confidence:.2f}",
            "symbol matched" if symbol in matched_symbols else "symbol not matched",
        ]
        risk_flags: list[str] = []
        if base_score < 40.0:
            risk_flags.append("low_skill_score")
        if confidence < 0.45:
            risk_flags.append("low_confidence")

        if score >= 65.0:
            decision = "PASS"
        elif score >= 45.0:
            decision = "WATCH"
        else:
            decision = "REJECT"

        return AnalyzerEvaluationV2(
            symbol=symbol,
            source_recommender=source_recommender,
            target_group=(str(target_group) if target_group in {"intersection", "top10"} else None),
            decision=decision,
            score=round(score, 2),
            reasons=reasons,
            risk_flags=risk_flags,
        )

    @staticmethod
    def _build_volatility_proxy(results: list[SkillRunResultV2]) -> dict[str, float]:
        values: dict[str, list[float]] = {}
        for result in results:
            payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
            for row in payload.get("top_candidates", [])[:30]:
                if not isinstance(row, dict):
                    continue
                symbol = _sanitize_symbol(row.get("symbol"))
                if not symbol:
                    continue
                vol = abs(_to_float(row.get("daily_return_pct"), 2.5))
                values.setdefault(symbol, []).append(vol)

        proxy: dict[str, float] = {}
        for symbol, nums in values.items():
            if not nums:
                continue
            proxy[symbol] = sum(nums) / len(nums)
        return proxy

    @staticmethod
    def _pick_primary_skill(
        by_slug: dict[str, SkillRunResultV2],
        requested: str,
    ) -> SkillRunResultV2 | None:
        requested_slug = requested.strip()
        if requested_slug:
            requested_item = by_slug.get(requested_slug)
            requested_trait = get_skill_trait(requested_slug) if requested_item else None
            if requested_item and requested_trait and requested_trait.recommendation_role in {"direct", "candidate"}:
                return requested_item

        recommended: list[SkillRunResultV2] = []
        for item in by_slug.values():
            trait = get_skill_trait(item.skill_slug)
            if trait is None:
                continue
            if trait.recommendation_role in {"direct", "candidate"}:
                recommended.append(item)
        if not recommended:
            return None

        def _rank(item: SkillRunResultV2) -> tuple[int, float]:
            trait = get_skill_trait(item.skill_slug)
            role_rank = 0 if trait and trait.recommendation_role == "direct" else 1
            return (role_rank, -(float(item.score_0_100 or 0.0)))

        recommended.sort(key=_rank)
        return recommended[0]

    @staticmethod
    def _pick_confirm_skills(
        by_slug: dict[str, SkillRunResultV2],
        primary_slug: str,
        requested: list[str],
    ) -> list[str]:
        if requested:
            valid: list[str] = []
            for slug in requested:
                if slug == primary_slug:
                    continue
                if slug not in by_slug:
                    continue
                trait = get_skill_trait(slug)
                if trait is None or trait.recommendation_role not in {"direct", "candidate"}:
                    continue
                valid.append(slug)
            return valid[:2]

        ranked: list[tuple[float, str]] = []
        for slug, result in by_slug.items():
            if slug == primary_slug:
                continue
            trait = get_skill_trait(slug)
            if trait is None or trait.recommendation_role not in {"direct", "candidate"}:
                continue
            ranked.append((float(result.score_0_100 or 0.0), slug))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [slug for _, slug in ranked[:2]]

    @staticmethod
    def _pick_analysis_skills(
        by_slug: dict[str, SkillRunResultV2],
        requested: list[str],
    ) -> list[str]:
        if requested:
            valid: list[str] = []
            for slug in requested:
                if slug not in by_slug:
                    continue
                trait = get_skill_trait(slug)
                if trait is None or trait.recommendation_role != "analysis_only":
                    continue
                valid.append(slug)
            return valid

        fallback: list[str] = []
        for slug, _result in by_slug.items():
            trait = get_skill_trait(slug)
            if trait and trait.recommendation_role == "analysis_only":
                fallback.append(slug)
        return fallback[:4]


def _max_state(current: str, incoming: str) -> str:
    order = {"unavailable": 0, "stale": 1, "live": 2}
    return incoming if order.get(incoming, 0) > order.get(current, 0) else current


def _sanitize_selected_skills(raw_slugs: list[str]) -> list[str]:
    if not raw_slugs:
        return []
    selected: list[str] = []
    for raw in raw_slugs[:128]:
        slug = str(raw).strip()
        if not slug or len(slug) > 80 or slug in selected:
            continue
        selected.append(slug)
    return selected


def _sanitize_watchlist(raw_symbols: list[str]) -> list[str]:
    if not raw_symbols:
        return []

    symbols: list[str] = []
    for raw in raw_symbols[:200]:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in symbols:
            continue
        if len(symbol) > 10:
            continue
        if re.fullmatch(r"[A-Z0-9.\-]+", symbol) is None:
            continue
        symbols.append(symbol)
    return symbols


def _sanitize_top_picks_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 5
    return max(1, min(50, parsed))


def _sanitize_slugs(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[\s,]+", value)
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = []

    parsed: list[str] = []
    for item in raw[:100]:
        slug = str(item).strip()
        if not slug or slug in parsed:
            continue
        if len(slug) > 80:
            continue
        if re.fullmatch(r"[a-z0-9\-]+", slug) is None:
            continue
        parsed.append(slug)
    return parsed


def _sanitize_min_confirm_votes(value: Any) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(5, parsed))


def _sanitize_recommender_top_n(value: Any) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = 25
    return max(5, min(50, parsed))


def _sanitize_analyzer_pass_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    if policy in {"all_pass", "pass_or_watch"}:
        return policy
    return "all_pass"


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _sanitize_symbol(raw: Any) -> str:
    symbol = str(raw or "").strip().upper()
    if not symbol:
        return ""
    if symbol in INVALID_SYMBOL_TOKENS:
        return ""
    if len(symbol) > 10:
        return ""
    if re.fullmatch(r"[A-Z0-9.\-]+", symbol) is None:
        return ""
    return symbol


def _percentile(rank_idx: int, total_count: int) -> float:
    if total_count <= 1:
        return 100.0
    return ((total_count - rank_idx - 1) / (total_count - 1)) * 100.0


def _extract_symbols_from_payload(payload: dict[str, Any]) -> list[str]:
    symbols: list[str] = []

    def _add(raw: Any) -> None:
        symbol = _sanitize_symbol(raw)
        if not symbol:
            return
        if symbol in symbols:
            return
        symbols.append(symbol)

    _add(payload.get("ticker"))

    for key in ("top_candidates", "targets", "candidates", "earnings"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows[:30]:
            if not isinstance(row, dict):
                continue
            _add(row.get("symbol"))
            _add(row.get("ticker"))

    ranked_events = payload.get("ranked_events")
    if isinstance(ranked_events, list):
        for row in ranked_events[:30]:
            if not isinstance(row, dict):
                continue
            for related in row.get("related_tickers", [])[:3]:
                _add(related)

    return symbols
