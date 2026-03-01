from __future__ import annotations

from typing import Any, Callable

from trading_skills_engine.skills_v2.contracts import SkillRunResultV2


def extract_ranked_symbols_for_recommender(
    result: SkillRunResultV2,
    top_n: int,
    sanitize_symbol: Callable[[Any], str],
    to_float: Callable[[Any, float], float],
    extract_symbols_from_payload: Callable[[dict[str, Any]], list[str]],
) -> list[tuple[str, float, str]]:
    payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
    ranked: dict[str, tuple[float, str]] = {}

    def _put(raw_symbol: Any, raw_score: Any, reason: str) -> None:
        symbol = sanitize_symbol(raw_symbol)
        if not symbol:
            return
        score = to_float(raw_score, 0.0)
        current = ranked.get(symbol)
        if current is None or score > current[0]:
            ranked[symbol] = (score, reason)

    _put(payload.get("ticker"), result.score_0_100 or 55.0, "ticker")

    for idx, row in enumerate(payload.get("top_candidates", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        if row.get("composite_score") is not None:
            score = to_float(row.get("composite_score"), 0.0)
            reason = "top_candidates"
        elif row.get("score") is not None:
            score = to_float(row.get("score"), 0.0)
            reason = "top_candidates_score"
        else:
            ai = max(0.0, min(1.0, to_float(row.get("ai_factor"), 0.5)))
            momentum = max(-15.0, min(20.0, to_float(row.get("momentum_20d"), 0.0)))
            daily = max(-12.0, min(12.0, to_float(row.get("daily_return_pct"), 0.0)))
            # Avoid synthetic fixed ladder (80,79,...) when upstream score fields are missing.
            score = 45.0 + ai * 30.0 + momentum * 1.4 + daily * 1.1 - idx * 0.3
            reason = "top_candidates_derived"
        _put(row.get("symbol"), max(0.0, min(100.0, score)), reason)

    for idx, row in enumerate(payload.get("leaders", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        if row.get("score") is not None:
            score = to_float(row.get("score"), 0.0)
            reason = "leaders_score"
        else:
            ai = max(0.0, min(1.0, to_float(row.get("ai_factor"), 0.5)))
            momentum = max(-15.0, min(20.0, to_float(row.get("momentum_20d"), 0.0)))
            daily = max(-12.0, min(12.0, to_float(row.get("daily_return_pct"), 0.0)))
            score = 42.0 + ai * 28.0 + momentum * 1.3 + daily * 1.0 - idx * 0.35
            reason = "leaders_derived"
        _put(row.get("symbol"), max(0.0, min(100.0, score)), reason)

    for idx, row in enumerate(payload.get("targets", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        weight = max(0.0, min(100.0, to_float(row.get("target_weight_pct"), 0.0)))
        ai = max(0.0, min(1.0, to_float(row.get("ai_factor"), 0.5)))
        momentum = max(-15.0, min(20.0, to_float(row.get("momentum_20d"), 0.0)))
        score = 38.0 + weight * 0.7 + ai * 12.0 + momentum * 0.6 - idx * 0.25
        _put(row.get("symbol"), max(0.0, min(100.0, score)), "targets")

    for idx, row in enumerate(payload.get("candidates", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        if row.get("setup_score") is not None:
            score = to_float(row.get("setup_score"), 0.0)
            reason = "candidates_setup"
        elif row.get("score") is not None:
            score = to_float(row.get("score"), 0.0)
            reason = "candidates_score"
        else:
            ai = max(0.0, min(1.0, to_float(row.get("ai_factor"), 0.5)))
            momentum = max(-15.0, min(20.0, to_float(row.get("momentum_20d"), 0.0)))
            daily = max(-12.0, min(12.0, to_float(row.get("daily_return_pct"), 0.0)))
            score = 41.0 + ai * 24.0 + momentum * 1.2 + daily * 0.9 - idx * 0.3
            reason = "candidates_derived"
        _put(row.get("symbol") or row.get("ticker"), max(0.0, min(100.0, score)), reason)

    for idx, row in enumerate(payload.get("earnings", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        market_cap = to_float(row.get("market_cap"), 0.0)
        _put(row.get("ticker"), min(100.0, 35.0 + market_cap / 50_000_000_000), "earnings")

    for idx, row in enumerate(payload.get("ranked_events", [])[: top_n * 3]):
        if not isinstance(row, dict):
            continue
        impact = to_float(row.get("impact_score"), 0.0)
        for related in row.get("related_tickers", [])[:3]:
            _put(related, min(100.0, 45.0 + impact * 12.0 - idx * 0.5), "ranked_events")

    for idx, symbol in enumerate(extract_symbols_from_payload(payload)[: top_n * 3]):
        sanitized = sanitize_symbol(symbol)
        if not sanitized:
            continue
        # payload_extract is a low-priority backfill and must not overwrite
        # richer sources like top_candidates/earnings/ranked_events.
        if sanitized in ranked:
            continue
        _put(sanitized, max(0.0, 38.0 - idx), "payload_extract")

    sorted_rows = sorted(ranked.items(), key=lambda item: item[1][0], reverse=True)[:top_n]
    return [(symbol, score_reason[0], score_reason[1]) for symbol, score_reason in sorted_rows]

