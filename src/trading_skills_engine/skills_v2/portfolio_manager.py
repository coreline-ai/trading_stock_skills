from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class PortfolioManagerAnalyzer(SkillAnalyzer):
    slug = "portfolio-manager"
    _CACHE_REVISION = 2

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        risk_profile = str(params.get("risk_profile") or "balanced").strip().lower()
        risk_profile = risk_profile if risk_profile in {"aggressive", "balanced", "defensive"} else "balanced"
        market_scope = str(context.market_provider.get_market_scope() or "US").upper()

        cache_key = _cache_key(
            self.slug,
            {
                "as_of": context.as_of_date.isoformat(),
                "risk_profile": risk_profile,
                "market_scope": market_scope,
                "cache_revision": self._CACHE_REVISION,
            },
        )
        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), "stale")

        try:
            state, source = context.market_provider.load_market_state_with_source()
        except Exception:
            scope = str(context.market_provider.get_market_scope() or "US").upper()
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko=f"{scope} 유니버스를 불러오지 못해 포트폴리오 제안을 수행할 수 없습니다.",
                reason_code="UNIVERSE_LOAD_FAILED",
                source_statuses={"fmp": "unavailable"},
            )
        source_state = "live" if source == "fmp_live" else "stale"

        targets = _build_targets(state.symbols, risk_profile=risk_profile)
        cash_buffer = _cash_buffer(state.vix_level, state.recession_risk, risk_profile)

        payload = {
            "risk_profile": risk_profile,
            "cash_buffer_pct": cash_buffer,
            "equity_allocation_pct": round(max(0.0, 100.0 - cash_buffer), 2),
            "targets": targets,
            "risk_controls": [
                "단일 종목 최대 비중 20%",
                "손절 -7% / 이익 보호 트레일링 병행",
                "VIX 급등 시 현금 비중 단계적 확대",
            ],
        }

        saved = context.cache_store.set(cache_key, payload, ttl_hours=12)
        return self._build_ok(payload, CacheStore.cache_info("fresh", saved), source_state)

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], source_state: str) -> SkillRunResultV2:
        targets = payload.get("targets", [])
        diversification = min(1.0, len(targets) / 8.0)
        cash_buffer = _to_float(payload.get("cash_buffer_pct"), 20.0)

        # Higher score means more deployable portfolio state.
        score = 55.0 + diversification * 20.0 - max(0.0, cash_buffer - 20.0) * 0.4
        score = max(0.0, min(100.0, score))

        confidence = 0.76 if source_state == "live" else 0.64
        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=(
                f"{payload.get('risk_profile')} 프로필 기준 목표 포트폴리오 "
                f"{len(targets)}종목을 제안했습니다."
            ),
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": source_state},
        )


def _build_targets(symbols: list[Any], risk_profile: str) -> list[dict[str, Any]]:
    if not symbols:
        return []

    ranked = sorted(
        symbols,
        key=lambda x: (x.ai_factor * 100 + x.momentum_20d * 1.5 + x.daily_return_pct),
        reverse=True,
    )

    if risk_profile == "aggressive":
        count = 6
    elif risk_profile == "defensive":
        count = 10
    else:
        count = 8

    picked = ranked[:count]
    raw_weights = [max(0.1, item.ai_factor + max(0.0, item.momentum_20d) / 20.0) for item in picked]
    total = sum(raw_weights)

    rows: list[dict[str, Any]] = []
    for item, weight in zip(picked, raw_weights):
        rows.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "sector": item.sector,
                "target_weight_pct": round((weight / total) * 100, 2),
                "momentum_20d": round(item.momentum_20d, 2),
                "ai_factor": round(item.ai_factor, 3),
            }
        )

    return rows


def _cash_buffer(vix_level: float, recession_risk: float, risk_profile: str) -> float:
    base = {"aggressive": 8.0, "balanced": 15.0, "defensive": 25.0}[risk_profile]
    vix_adj = max(0.0, vix_level - 18.0) * 1.2
    macro_adj = max(0.0, recession_risk - 0.3) * 40.0
    return round(max(3.0, min(45.0, base + vix_adj + macro_adj)), 2)


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"
