from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.core.models import SkillDefinition, SymbolSignal
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2
from trading_skills_engine.skills_v2.traits import get_skill_trait


class ProxySkillAnalyzer(SkillAnalyzer):
    """Market-state-backed proxy analyzer for catalog slugs without dedicated implementations."""

    _CACHE_REVISION = 4

    def __init__(self, definition: SkillDefinition) -> None:
        self.definition = definition
        self.slug = definition.slug

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        horizon_days = _clamp_int(params.get("horizon_days"), 20, lo=1, hi=180)
        risk_tilt = str(params.get("risk_tilt") or "balanced").strip().lower()
        if risk_tilt not in {"defensive", "balanced", "aggressive"}:
            risk_tilt = "balanced"
        profile = _build_skill_profile(self.definition.slug)
        profile_signature = _profile_signature(profile)

        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "horizon_days": horizon_days,
                "risk_tilt": risk_tilt,
                "profile_signature": profile_signature,
                "cache_revision": self._CACHE_REVISION,
            },
        )

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            payload = cached.payload if isinstance(cached.payload, dict) else {}
            source_state = str(payload.get("_source_state") or "stale")
            if source_state == "live" and context.market_provider.client is None:
                source_state = "stale"
            return self._build_ok(payload, cache_info={
                "mode": "fresh",
                "fetched_at": cached.fetched_at.isoformat(),
                "expires_at": cached.expires_at.isoformat(),
            }, source_state=source_state)

        try:
            state, source = _get_shared_market_state(context)
        except Exception:
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="프록시 시장 상태를 불러오지 못해 분석할 수 없습니다.",
                reason_code="PROXY_STATE_UNAVAILABLE",
                source_statuses={"fmp": "unavailable"},
            )

        source_state = "live" if source == "fmp_live" else "stale"
        axis_scores = _compute_axis_scores(state.symbols, list(profile["axis_weights"].keys()))
        style = str(profile.get("style") or "")
        signals = [str(item) for item in (profile.get("signals") or [])]
        composite_by_symbol: dict[str, float] = {}
        for item in state.symbols:
            base_composite = _composite_symbol_score(item.symbol, profile["axis_weights"], axis_scores)
            style_adjust = _style_symbol_adjustment(
                style=style,
                signals=signals,
                item=item,
                state=state,
            )
            composite_by_symbol[item.symbol] = (
                base_composite
                + style_adjust
                + _skill_symbol_bias(self.slug, item.symbol, amplitude=2.0)
            )
        ranked = sorted(state.symbols, key=lambda item: composite_by_symbol.get(item.symbol, 50.0), reverse=True)

        focus_count = _focus_count_for_style(
            style=style,
            recommendation_role=str(profile.get("recommendation_role") or ""),
            risk_tilt=risk_tilt,
            universe_size=len(ranked),
        )
        focus = ranked[:focus_count]

        leadership_score = _leadership_score_from_map(focus=focus, composite_by_symbol=composite_by_symbol)
        market_fit = _market_fit(profile["signals"], state)
        score = max(
            0.0,
            min(
                100.0,
                20.0 + leadership_score * 0.65 + market_fit + _skill_slug_bias(self.slug, amplitude=2.5),
            ),
        )
        confidence = 0.6 + (0.14 if source_state == "live" else 0.05)
        confidence += min(0.18, len(profile["axis_weights"]) * 0.03)
        confidence += _skill_slug_bias(self.slug, amplitude=0.02)
        confidence = max(0.35, min(0.92, confidence))

        payload = {
            "mode": "proxy_market_state_v2",
            "skill_slug": self.slug,
            "family": self.definition.family,
            "methodology": self.definition.methodology,
            "profile": profile,
            "recommendation_role": profile.get("recommendation_role"),
            "consensus_weight": profile.get("consensus_weight"),
            "risk_tilt": risk_tilt,
            "horizon_days": horizon_days,
            "as_of_date": context.as_of_date.isoformat(),
            "regime": _regime_label(state.breadth_up_ratio, state.vix_level, state.recession_risk),
            "score_breakdown": {
                "leadership": round(leadership_score, 2),
                "market_fit": round(market_fit, 2),
            },
            "market_snapshot": {
                "spy_return_1d": state.spy_return_1d,
                "qqq_return_1d": state.qqq_return_1d,
                "iwm_return_1d": state.iwm_return_1d,
                "tlt_return_1d": state.tlt_return_1d,
                "vix_level": state.vix_level,
                "breadth_up_ratio": state.breadth_up_ratio,
                "recession_risk": state.recession_risk,
            },
            "top_candidates": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "daily_return_pct": round(item.daily_return_pct, 2),
                    "momentum_20d": round(item.momentum_20d, 2),
                    "ai_factor": round(item.ai_factor, 3),
                    "composite_score": round(composite_by_symbol.get(item.symbol, 50.0), 2),
                }
                for item in focus
            ],
            "execution_notes": _execution_notes(self.definition.family, risk_tilt),
            "score_0_100": round(score, 2),
            "confidence_0_1": round(confidence, 2),
            "_source_state": source_state,
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=12)
        return self._build_ok(
            payload,
            cache_info={
                "mode": "fresh",
                "fetched_at": saved.fetched_at.isoformat(),
                "expires_at": saved.expires_at.isoformat(),
            },
            source_state=source_state,
        )

    def _build_ok(
        self,
        payload: dict[str, Any],
        cache_info: dict[str, str | None],
        source_state: str,
    ) -> SkillRunResultV2:
        regime = str(payload.get("regime") or "Balanced")
        top_candidates = payload.get("top_candidates", [])
        top_symbol = top_candidates[0]["symbol"] if top_candidates and isinstance(top_candidates[0], dict) else "-"
        profile = payload.get("profile", {})
        style = str(profile.get("style") or "generic")
        score = _to_float(payload.get("score_0_100"), 55.0)
        confidence = _to_float(payload.get("confidence_0_1"), 0.58)

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(max(0.0, min(100.0, score)), 2),
            confidence_0_1=round(max(0.3, min(0.95, confidence)), 2),
            summary_ko=(
                f"{self.definition.display_name} 프록시 분석 완료: {regime} 레짐, {style} 스타일, 우선 후보 {top_symbol}"
            ),
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def build_proxy_analyzers(excluded_slugs: set[str]) -> dict[str, SkillAnalyzer]:
    analyzers: dict[str, SkillAnalyzer] = {}
    for definition in SKILL_CATALOG:
        if definition.slug in excluded_slugs:
            continue
        analyzers[definition.slug] = ProxySkillAnalyzer(definition)
    return analyzers


def _get_shared_market_state(context: AnalyzerContext) -> tuple[Any, str]:
    # Cache market state per run context to avoid repetitive external calls.
    snapshot = getattr(context, "_shared_market_state_snapshot", None)
    if snapshot is not None:
        return snapshot

    state, source = context.market_provider.load_market_state_with_source()
    setattr(context, "_shared_market_state_snapshot", (state, source))
    return state, source


def _build_skill_profile(slug: str) -> dict[str, Any]:
    trait = get_skill_trait(slug)
    if trait is None:
        return {
            "style": "generic",
            "axis_weights": {"trend_score": 0.5, "quality_score": 0.5},
            "signals": ["risk_neutral"],
            "recommendation_role": "analysis_only",
            "consensus_weight": 1.0,
        }

    return {
        "style": trait.style,
        "axis_weights": dict(trait.axis_weights),
        "signals": list(trait.signals),
        "recommendation_role": trait.recommendation_role,
        "consensus_weight": trait.consensus_weight,
    }


def _profile_signature(profile: dict[str, Any]) -> str:
    payload = {
        "style": str(profile.get("style") or ""),
        "axis_weights": dict(profile.get("axis_weights") or {}),
        "signals": list(profile.get("signals") or []),
        "recommendation_role": str(profile.get("recommendation_role") or ""),
        "consensus_weight": float(profile.get("consensus_weight") or 0.0),
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _compute_axis_scores(symbols: list[SymbolSignal], axes: list[str]) -> dict[str, dict[str, float]]:
    axis_scores: dict[str, dict[str, float]] = {}
    for axis in axes:
        pairs: list[tuple[str, float]] = []
        for item in symbols:
            pairs.append((item.symbol, _axis_raw(item, axis)))
        pairs.sort(key=lambda x: x[1], reverse=True)
        size = len(pairs)
        scored: dict[str, float] = {}
        for idx, (symbol, _) in enumerate(pairs):
            if size <= 1:
                scored[symbol] = 100.0
            else:
                scored[symbol] = ((size - idx - 1) / (size - 1)) * 100.0
        axis_scores[axis] = scored
    return axis_scores


def _axis_raw(item: SymbolSignal, axis: str) -> float:
    sector = item.sector.lower()
    defensive_sector = any(key in sector for key in ("health", "consumer", "utility", "staple", "real estate"))
    defensive_bonus = 8.0 if defensive_sector else 0.0

    trend = item.momentum_20d * 1.1 + item.daily_return_pct * 0.9 + item.ai_factor * 15.0
    breakout = max(0.0, item.momentum_20d) * 1.4 + max(0.0, item.daily_return_pct) * 2.0 + item.ai_factor * 20.0
    quality = item.ai_factor * 100.0 - max(0.0, abs(item.daily_return_pct) - 4.0) * 2.0
    stability = 100.0 - (abs(item.daily_return_pct) * 4.0 + abs(item.momentum_20d) * 0.9) + defensive_bonus
    oversold = max(0.0, -item.momentum_20d) * 1.5 + max(0.0, -item.daily_return_pct) * 2.5 + (100.0 - item.ai_factor * 100.0) * 0.1
    defensive = stability * 0.6 + (100.0 - item.ai_factor * 100.0) * 0.25 + defensive_bonus
    value = oversold * 0.55 + defensive * 0.45

    mapping = {
        "trend_score": trend,
        "breakout_score": breakout,
        "quality_score": quality,
        "stability_score": stability,
        "oversold_score": oversold,
        "defensive_score": defensive,
        "value_score": value,
    }
    return mapping.get(axis, trend)


def _composite_symbol_score(symbol: str, axis_weights: dict[str, float], axis_scores: dict[str, dict[str, float]]) -> float:
    values: list[float] = []
    weights: list[float] = []
    for axis, weight in axis_weights.items():
        values.append(float(axis_scores.get(axis, {}).get(symbol, 50.0)))
        weights.append(float(weight))
    if not values or not weights:
        return 50.0
    denominator = sum(weights)
    if denominator <= 0:
        return sum(values) / len(values)
    return sum(value * weight for value, weight in zip(values, weights)) / denominator


def _leadership_score(
    focus: list[SymbolSignal],
    axis_weights: dict[str, float],
    axis_scores: dict[str, dict[str, float]],
) -> float:
    if not focus:
        return 0.0
    avg = sum(_composite_symbol_score(item.symbol, axis_weights, axis_scores) for item in focus) / len(focus)
    return max(0.0, min(100.0, avg))


def _leadership_score_from_map(focus: list[SymbolSignal], composite_by_symbol: dict[str, float]) -> float:
    if not focus:
        return 0.0
    avg = sum(float(composite_by_symbol.get(item.symbol, 50.0)) for item in focus) / len(focus)
    return max(0.0, min(100.0, avg))


def _market_fit(signals: list[str], state: Any) -> float:
    fit = 0.0
    if "breadth_sensitive" in signals:
        fit += (state.breadth_up_ratio - 0.5) * 30.0
    if "risk_on" in signals:
        fit += max(0.0, 22.0 - state.vix_level) * 0.8
        fit += (state.spy_return_1d + state.qqq_return_1d + state.iwm_return_1d) * 0.9
    if "risk_off" in signals:
        fit += max(0.0, state.vix_level - 20.0) * 0.9
        fit += state.recession_risk * 12.0
    if "event_driven" in signals:
        fit += (abs(state.spy_return_1d) + abs(state.qqq_return_1d)) * 0.2
        fit += max(0.0, state.vix_level - 18.0) * 0.3
    if "rate_sensitive" in signals:
        fit += state.tlt_return_1d * 2.2
    return max(-15.0, min(15.0, fit))


def _regime_label(breadth: float, vix: float, recession_risk: float) -> str:
    if recession_risk >= 0.5:
        return "Contraction"
    if breadth >= 0.62 and vix < 22:
        return "Broadening"
    if vix >= 24:
        return "Transitional"
    return "Balanced"


def _execution_notes(family: str, risk_tilt: str) -> list[str]:
    notes = [
        "프록시 분석 결과이므로 실시간 원천 데이터와 교차 검증 필요",
        "단일 시그널 과신 금지, 포지션 사이징 규칙 준수",
    ]

    if family in {"market_timing", "strategy_risk"}:
        notes.append("노출 비중은 VIX/무효화 레벨 변화에 따라 단계적으로 조정")
    if family in {"screening", "earnings_momentum"}:
        notes.append("후보 종목은 유동성/실적 일정/갭 리스크를 확인 후 진입")
    if risk_tilt == "defensive":
        notes.append("방어형 프로필: 현금 비중 우선 유지")
    return notes


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    digest = sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{slug}:{digest}"


def _focus_count_for_style(
    style: str,
    recommendation_role: str,
    risk_tilt: str,
    universe_size: int,
) -> int:
    key = str(style or "").strip().lower()
    role = str(recommendation_role or "").strip().lower()
    base = 8
    if role == "direct":
        base = 9
    if key in {
        "technical_invalidation",
        "vcp_pattern",
        "follow_through_day",
        "trend_participation",
        "distribution_days",
        "post_earnings_gap",
    }:
        base = 7
    elif key in {
        "value_income",
        "dividend_pullback",
        "dividend_sop",
        "cointegration_reversion",
        "tax_accounting",
    }:
        base = 9

    if risk_tilt == "defensive":
        base += 1
    return max(5, min(max(1, universe_size), base))


def _style_symbol_adjustment(style: str, signals: list[str], item: SymbolSignal, state: Any) -> float:
    key = str(style or "").strip().lower()
    sector = str(item.sector or "").strip().lower()
    growth_sector = any(token in sector for token in ("tech", "semiconductor", "communication", "consumer", "automotive"))
    defensive_sector = any(token in sector for token in ("health", "utility", "staple", "real estate"))
    financial_sector = "financial" in sector

    ai = max(0.0, min(1.0, float(item.ai_factor)))
    momentum = max(-20.0, min(25.0, float(item.momentum_20d)))
    daily = max(-15.0, min(15.0, float(item.daily_return_pct)))

    adjust = 0.0
    signal_set = {str(sig).strip().lower() for sig in signals}
    if "risk_on" in signal_set:
        if growth_sector:
            adjust += 2.2
        adjust += max(0.0, momentum) * 0.12
    if "risk_off" in signal_set:
        if defensive_sector:
            adjust += 2.4
        if growth_sector:
            adjust -= 1.2
    if "event_driven" in signal_set and ("health" in sector or "tech" in sector):
        adjust += 0.9
    if "rate_sensitive" in signal_set and (financial_sector or "real estate" in sector):
        adjust += 1.0

    if key in {"technical_invalidation", "vcp_pattern", "follow_through_day", "trend_participation"}:
        adjust += max(0.0, momentum) * 0.45 + max(0.0, daily) * 0.9 - max(0.0, -daily) * 0.5
        adjust += ai * 2.0
    elif key in {"value_income", "dividend_pullback", "dividend_sop", "cointegration_reversion", "tax_accounting"}:
        adjust += max(0.0, -momentum) * 0.55 + max(0.0, -daily) * 0.85 + (1.0 - ai) * 5.5
        if defensive_sector:
            adjust += 1.2
    elif key in {"sector_rotation", "breadth_phase", "breadth_factor"}:
        adjust += momentum * 0.3 + ai * 1.8 + (float(state.breadth_up_ratio) - 0.5) * 7.0
    elif key in {"cross_asset_regime", "macro_regime", "macro_event_window"}:
        stability = 100.0 - (abs(daily) * 4.0 + abs(momentum) * 0.9)
        adjust += (stability - 50.0) * 0.08 + float(state.tlt_return_1d) * 0.6 - (float(state.vix_level) - 20.0) * 0.08

    # Deterministic tie-breaker avoids repeated equal-order outputs across styles.
    adjust += _style_symbol_bias(style, item.symbol, amplitude=1.2)
    return max(-18.0, min(18.0, adjust))


def _style_symbol_bias(style: str, symbol: str, amplitude: float) -> float:
    digest = sha256(f"{style}:{symbol}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    centered = (bucket * 2.0) - 1.0
    return centered * float(amplitude)


def _skill_slug_bias(slug: str, amplitude: float) -> float:
    digest = sha256(slug.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    centered = (bucket * 2.0) - 1.0
    return centered * float(amplitude)


def _skill_symbol_bias(slug: str, symbol: str, amplitude: float) -> float:
    digest = sha256(f"{slug}:{symbol}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    centered = (bucket * 2.0) - 1.0
    return centered * float(amplitude)


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(hi, parsed))


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
