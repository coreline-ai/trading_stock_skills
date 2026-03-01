from __future__ import annotations

from typing import Any, Callable

from trading_skills_engine.skills_v2.contracts import AnalyzerEvaluationV2, SkillRunResultV2


def analyzer_style_weights(style: str) -> dict[str, float]:
    key = str(style or "").strip().lower()
    presets: dict[str, dict[str, float]] = {
        # 환경/자산배분 성격: 모멘텀보다는 안정성/컨텍스트 가중
        "cross_asset_regime": {
            "base": 1.08,
            "confidence": 1.12,
            "match": 1.0,
            "rank": 0.78,
            "ai": 0.86,
            "momentum": 0.35,
        },
        # 매크로 레짐 성격: 추세/랭크 기여를 더 반영
        "macro_regime": {
            "base": 1.0,
            "confidence": 1.0,
            "match": 1.0,
            "rank": 1.08,
            "ai": 1.0,
            "momentum": 0.82,
        },
    }
    base = {"base": 1.0, "confidence": 1.0, "match": 1.0, "rank": 1.0, "ai": 1.0, "momentum": 1.0}
    selected = presets.get(key)
    if not selected:
        return base
    merged = dict(base)
    merged.update(selected)
    return merged


def evaluate_symbol_for_analyzer(
    symbol: str,
    result: SkillRunResultV2,
    get_skill_trait: Callable[[str], Any],
    sanitize_symbol: Callable[[Any], str],
    to_float: Callable[[Any, float], float],
    extract_symbols_from_payload: Callable[[dict[str, Any]], list[str]],
    source_recommender: str | None = None,
    target_group: str | None = None,
    symbol_strength_0_100: float | None = None,
) -> AnalyzerEvaluationV2:
    del symbol_strength_0_100
    payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
    matched_symbols = set(extract_symbols_from_payload(payload))
    candidate_rows = payload.get("top_candidates")
    candidate_rows = candidate_rows if isinstance(candidate_rows, list) else []
    candidate_rank: dict[str, int] = {}
    candidate_ai: dict[str, float] = {}
    candidate_momentum: dict[str, float] = {}
    for idx, row in enumerate(candidate_rows[:50]):
        if not isinstance(row, dict):
            continue
        row_symbol = sanitize_symbol(row.get("symbol"))
        if not row_symbol:
            continue
        if row_symbol not in candidate_rank:
            candidate_rank[row_symbol] = idx
        candidate_ai[row_symbol] = to_float(row.get("ai_factor"), 0.5)
        candidate_momentum[row_symbol] = to_float(row.get("momentum_20d"), 0.0)

    has_payload_symbol_signals = (
        symbol in matched_symbols
        or symbol in candidate_rank
        or symbol in candidate_ai
        or symbol in candidate_momentum
    )
    style = ""
    if (trait := get_skill_trait(result.skill_slug)) is not None:
        style = trait.style
    style_weights = analyzer_style_weights(style)
    base_score = to_float(result.score_0_100, 50.0)
    confidence = to_float(result.confidence_0_1, 0.5)
    # Macro/event analyzers often have no symbol-level payload; avoid uniform hard penalty.
    match_bonus = (10.0 if symbol in matched_symbols else -10.0) if has_payload_symbol_signals else 0.0

    rank_idx = candidate_rank.get(symbol)
    if rank_idx is None:
        rank_score = 0.0
    else:
        # Earlier rank in top_candidates gets higher contribution.
        rank_score = max(0.0, 16.0 - float(rank_idx) * 2.0)
    ai_score = max(0.0, min(1.0, candidate_ai.get(symbol, 0.5))) * 10.0
    momentum = max(-12.0, min(12.0, candidate_momentum.get(symbol, 0.0)))
    momentum_score = momentum * 0.4
    score = (
        base_score * 0.42 * style_weights["base"]
        + confidence * 100.0 * 0.18 * style_weights["confidence"]
        + match_bonus * style_weights["match"]
        + rank_score * style_weights["rank"]
        + ai_score * style_weights["ai"]
        + momentum_score * style_weights["momentum"]
    )
    score = max(0.0, min(100.0, score))

    reasons: list[str] = [
        f"base {base_score:.1f}",
        f"confidence {confidence:.2f}",
        (
            "symbol matched"
            if symbol in matched_symbols
            else ("symbol not matched" if has_payload_symbol_signals else "symbol_signal absent")
        ),
        f"rank_bonus {rank_score:.1f}" if rank_idx is not None else "rank_bonus 0.0",
        f"ai_factor {candidate_ai.get(symbol, 0.5):.2f}",
        f"momentum_20d {candidate_momentum.get(symbol, 0.0):.2f}",
    ]
    if style:
        reasons.append(f"style {style}")
        reasons.append(
            f"style_weights rank {style_weights['rank']:.2f} ai {style_weights['ai']:.2f} momentum {style_weights['momentum']:.2f}"
        )
    risk_flags: list[str] = []
    if base_score < 40.0:
        risk_flags.append("low_skill_score")
    if confidence < 0.45:
        risk_flags.append("low_confidence")
    if not has_payload_symbol_signals:
        risk_flags.append("symbol_signal_absent")

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


def build_volatility_proxy(
    results: list[SkillRunResultV2],
    sanitize_symbol: Callable[[Any], str],
    to_float: Callable[[Any, float], float],
) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for result in results:
        payload = result.analysis_payload if isinstance(result.analysis_payload, dict) else {}
        for row in payload.get("top_candidates", [])[:30]:
            if not isinstance(row, dict):
                continue
            symbol = sanitize_symbol(row.get("symbol"))
            if not symbol:
                continue
            vol = abs(to_float(row.get("daily_return_pct"), 2.5))
            values.setdefault(symbol, []).append(vol)

    proxy: dict[str, float] = {}
    for symbol, nums in values.items():
        if not nums:
            continue
        proxy[symbol] = sum(nums) / len(nums)
    return proxy


def build_rank_rows(
    symbols: list[str],
    target_group: str,
    support_count_all: dict[str, int],
    analyzer_scores_by_target_symbol: dict[str, dict[str, dict[str, float]]],
    volatility_proxy: dict[str, float],
) -> list[dict[str, Any]]:
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

