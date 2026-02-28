from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class USStockAnalysisAnalyzer(SkillAnalyzer):
    slug = "us-stock-analysis"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        ticker = str(params.get("ticker") or "").upper().strip()
        if not ticker:
            state = context.market_provider.load_market_state()
            ticker = max(state.symbols, key=lambda x: x.ai_factor).symbol if state.symbols else "AAPL"

        cache_key = _cache_key(self.slug, {"ticker": ticker})
        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            payload = cached.payload if isinstance(cached.payload, dict) else {}
            fmp_state = str(payload.get("_source_state") or "stale")
            if fmp_state == "live" and context.fmp_news is None:
                fmp_state = "stale"
            if not (context.fmp_news is not None and fmp_state != "live"):
                return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), fmp_state)

        if context.fmp_news is None:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            proxy_payload = self._build_proxy_payload_from_market_state(ticker=ticker, context=context)
            saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=24)
            return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "stale")

        try:
            quote = context.fmp_news.get_quote(ticker) or {}
            profile = context.fmp_news.get_profile(ticker) or {}
            metrics = context.fmp_news.get_key_metrics_ttm(ticker) or {}
            peers = context.fmp_news.get_peers(ticker)

            if not quote and not profile and not metrics and not peers:
                stale = context.cache_store.get_stale(cache_key)
                if stale and _source_state(stale.payload) == "live":
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
                proxy_payload = self._build_proxy_payload_from_market_state(ticker=ticker, context=context)
                context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> proxy 사용")
                saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=24)
                return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "unavailable")

            payload = self._build_payload(ticker, quote, profile, metrics, peers)
            if not payload.get("ticker"):
                raise ValueError("empty")

            payload["_source_state"] = "live"
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live")
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            proxy_payload = self._build_proxy_payload_from_market_state(ticker=ticker, context=context)
            context.warnings.append(f"{self.slug}: FETCH_FAILED -> proxy 사용")
            saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=24)
            return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "unavailable")

    def _build_payload(
        self,
        ticker: str,
        quote: dict[str, Any],
        profile: dict[str, Any],
        metrics: dict[str, Any],
        peers: list[str],
    ) -> dict[str, Any]:
        price = _to_float(quote.get("price"), 0.0)
        change_pct = _to_float(quote.get("changePercentage") or quote.get("changesPercentage"), 0.0)
        pe = _to_float(metrics.get("peRatioTTM") or metrics.get("peRatio"), 0.0)
        if pe <= 0:
            earnings_yield = _to_float(metrics.get("earningsYieldTTM"), 0.0)
            pe = (1 / earnings_yield) if earnings_yield > 0 else 0.0
        roe = _to_float(metrics.get("returnOnEquityTTM") or metrics.get("roeTTM") or metrics.get("roe"), 0.0)
        debt_to_equity = _to_float(metrics.get("debtToEquityTTM") or metrics.get("debtToEquity"), 0.0)

        bullish = []
        bearish = []

        if change_pct > 0:
            bullish.append("단기 모멘텀이 플러스입니다.")
        else:
            bearish.append("단기 수익률이 약세입니다.")

        if roe >= 0.15:
            bullish.append("ROE가 상대적으로 높아 수익성 품질이 양호합니다.")
        if debt_to_equity > 2.0:
            bearish.append("부채비율이 높아 금리 민감 리스크가 있습니다.")

        risk_items = [
            "실적 가이던스 하향 가능성",
            "밸류에이션 리레이팅 변동성",
        ]

        return {
            "ticker": ticker,
            "fundamentals": {
                "company": str(profile.get("companyName") or profile.get("name") or ticker),
                "market_cap": _to_float(profile.get("marketCap") or profile.get("mktCap"), 0.0),
                "sector": str(profile.get("sector") or ""),
                "industry": str(profile.get("industry") or ""),
                "pe_ratio": pe,
                "roe": roe,
                "debt_to_equity": debt_to_equity,
            },
            "technicals": {
                "price": price,
                "day_change_pct": change_pct,
                "year_high": _to_float(quote.get("yearHigh"), 0.0),
                "year_low": _to_float(quote.get("yearLow"), 0.0),
            },
            "peer_snapshot": peers[:10],
            "bull_case": bullish or ["재무/모멘텀 데이터 보강 필요"],
            "bear_case": bearish or ["단기 과열 가능성 점검 필요"],
            "risk_items": risk_items,
            "citations": [
                f"https://financialmodelingprep.com/quote/{ticker}",
                f"https://financialmodelingprep.com/profile/{ticker}",
            ],
        }

    def _build_proxy_payload_from_market_state(self, ticker: str, context: AnalyzerContext) -> dict[str, Any]:
        state = context.market_provider.load_market_state()
        by_symbol = {item.symbol.upper(): item for item in state.symbols}
        selected = by_symbol.get(ticker.upper())
        if selected is None:
            selected = max(state.symbols, key=lambda x: x.ai_factor) if state.symbols else None

        if selected is None:
            selected_ticker = ticker or "AAPL"
            return {
                "ticker": selected_ticker,
                "fundamentals": {
                    "company": selected_ticker,
                    "market_cap": 0.0,
                    "sector": "",
                    "industry": "",
                    "pe_ratio": 0.0,
                    "roe": 0.0,
                    "debt_to_equity": 0.0,
                },
                "technicals": {"price": 0.0, "day_change_pct": 0.0, "year_high": 0.0, "year_low": 0.0},
                "peer_snapshot": [],
                "bull_case": ["샘플 데이터가 부족해 보수적 해석이 필요합니다."],
                "bear_case": ["실데이터 부재로 신뢰도가 제한됩니다."],
                "risk_items": ["데이터 소스 제약 리스크"],
                "citations": [],
                "mode": "market_state_proxy",
                "_source_state": "stale",
            }

        selected_ticker = selected.symbol.upper()
        price = round(90.0 + selected.ai_factor * 180.0 + selected.momentum_20d * 2.0, 2)
        year_high = round(price * 1.18, 2)
        year_low = round(max(1.0, price * 0.78), 2)
        pe_ratio = round(14.0 + selected.ai_factor * 18.0, 2)
        roe = round(min(0.35, 0.08 + selected.ai_factor * 0.18), 3)
        debt_to_equity = round(max(0.3, 2.4 - selected.ai_factor * 2.0), 2)
        synthetic_cap = round(selected.ai_factor * 450_000_000_000 + (selected.momentum_20d + 10.0) * 2_000_000_000, 2)

        peers = [
            item.symbol
            for item in sorted(state.symbols, key=lambda x: (x.ai_factor * 100 + x.momentum_20d), reverse=True)
            if item.symbol != selected_ticker
        ][:10]

        bull = [
            "샘플 시장 상태에서 상대 모멘텀이 상위권입니다.",
            "AI factor 기반 상대 점수가 양호합니다.",
        ]
        bear = [
            "실시간 재무지표 확인 전 과신 금지",
            "이벤트 드리븐 변동성 가능성 점검 필요",
        ]

        return {
            "ticker": selected_ticker,
            "fundamentals": {
                "company": selected.name,
                "market_cap": synthetic_cap,
                "sector": selected.sector,
                "industry": selected.sector,
                "pe_ratio": pe_ratio,
                "roe": roe,
                "debt_to_equity": debt_to_equity,
            },
            "technicals": {
                "price": price,
                "day_change_pct": round(selected.daily_return_pct, 2),
                "year_high": year_high,
                "year_low": year_low,
            },
            "peer_snapshot": peers,
            "bull_case": bull,
            "bear_case": bear,
            "risk_items": [
                "실적 가이던스 확인 필요",
                "시장 레짐 반전 시 변동성 확대 가능",
            ],
            "citations": [],
            "mode": "market_state_proxy",
            "_source_state": "stale",
        }

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], fmp_state: str) -> SkillRunResultV2:
        fundamentals = payload.get("fundamentals", {})
        technicals = payload.get("technicals", {})

        roe = _to_float(fundamentals.get("roe"), 0.0)
        pe = _to_float(fundamentals.get("pe_ratio"), 0.0)
        chg = _to_float(technicals.get("day_change_pct"), 0.0)

        score = 55 + min(20, max(-10, chg * 3)) + min(15, roe * 40) - min(10, max(0, pe - 35) * 0.3)
        confidence = 0.55 + (0.15 if fundamentals.get("market_cap", 0) else 0) + (0.1 if technicals.get("price", 0) else 0)

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(max(0.0, min(100.0, score)), 2),
            confidence_0_1=round(max(0.3, min(0.95, confidence)), 2),
            summary_ko=f"{payload.get('ticker')}의 펀더멘털/테크니컬/피어 데이터를 통합 분석했습니다.",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": fmp_state},
        )


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"


def _source_state(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("_source_state") or "stale")
    return "stale"
