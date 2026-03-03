from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.error import HTTPError

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class USStockAnalysisAnalyzer(SkillAnalyzer):
    slug = "us-stock-analysis"
    _CACHE_REVISION = 2
    _DEFAULT_STALE_MAX_AGE_HOURS = 6.0

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        market_scope = str(context.market_provider.get_market_scope() or "US").upper()
        ticker = str(params.get("ticker") or "").upper().strip()
        if not ticker:
            try:
                state = context.market_provider.load_market_state()
            except Exception:
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko=f"{market_scope} 유니버스를 불러오지 못해 단일 종목 분석을 시작할 수 없습니다.",
                    reason_code="UNIVERSE_LOAD_FAILED",
                    source_statuses={"fmp": "unavailable"},
                )
            ticker = max(state.symbols, key=lambda x: x.ai_factor).symbol if state.symbols else ""
            if not ticker:
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="분석 가능한 종목이 없어 단일 종목 분석을 수행할 수 없습니다.",
                    reason_code="UNIVERSE_EMPTY",
                    source_statuses={"fmp": "unavailable"},
                )

        cache_key = _cache_key(
            self.slug,
            {
                "ticker": ticker,
                "market_scope": market_scope,
                "cache_revision": self._CACHE_REVISION,
            },
        )
        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            payload = cached.payload if isinstance(cached.payload, dict) else {}
            fmp_state = str(payload.get("_source_state") or "stale")
            if fmp_state == "live" and context.fmp_news is None:
                fmp_state = "stale"
            if not (context.fmp_news is not None and fmp_state != "live"):
                return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), fmp_state)

        stale_max_age_hours = _clamp_non_negative(
            _to_float(params.get("stale_max_age_hours"), self._DEFAULT_STALE_MAX_AGE_HOURS)
        )
        prefer_stale_cache = _to_bool(params.get("prefer_stale_cache"), default=True)
        stale = context.cache_store.get_stale(cache_key)
        if (
            prefer_stale_cache
            and stale
            and _source_state(stale.payload) == "live"
            and _cache_age_hours(stale.fetched_at) <= stale_max_age_hours
        ):
            context.warnings.append(
                f"{self.slug}: CACHE_FIRST_STALE age={_cache_age_hours(stale.fetched_at):.2f}h <= {stale_max_age_hours:.2f}h"
            )
            return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")

        if context.fmp_news is None:
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="FMP 연결 또는 stale 캐시가 없어 단일 종목 분석을 수행할 수 없습니다.",
                reason_code="NO_API_KEY_AND_NO_STALE_CACHE",
                source_statuses={"fmp": "unavailable"},
            )

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
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="원천 데이터가 비어 있어 단일 종목 분석을 수행할 수 없습니다.",
                    reason_code="EMPTY_SOURCE",
                    source_statuses={"fmp": "unavailable"},
                )

            payload = self._build_payload(ticker, quote, profile, metrics, peers)
            if not payload.get("ticker"):
                raise ValueError("empty")

            payload["_source_state"] = "live"
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live")
        except HTTPError as exc:
            stale = context.cache_store.get_stale(cache_key)
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: HTTP_{exc.code} -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            if exc.code == 429:
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="FMP API 호출 제한(HTTP 429)으로 단일 종목 데이터 조회에 실패했습니다. 잠시 후 재시도하거나 stale 캐시를 확보하세요.",
                    reason_code="FMP_HTTP_429",
                    source_statuses={"fmp": "unavailable"},
                )
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko=f"FMP HTTP 오류({exc.code})로 단일 종목 데이터 조회에 실패했습니다.",
                reason_code=f"FMP_HTTP_{exc.code}",
                source_statuses={"fmp": "unavailable"},
            )
        except RuntimeError as exc:
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: {exc} -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            if str(exc) == "FMP_HTTP_429":
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="FMP API 호출 제한(HTTP 429)으로 단일 종목 데이터 조회에 실패했습니다. 잠시 후 재시도하거나 stale 캐시를 확보하세요.",
                    reason_code="FMP_HTTP_429",
                    source_statuses={"fmp": "unavailable"},
                )
            if str(exc) == "FMP_RATE_LIMIT_COOLDOWN":
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="FMP 429 쿨다운이 진행 중이라 라이브 조회를 건너뛰었습니다. 잠시 후 재시도하거나 stale 캐시를 사용하세요.",
                    reason_code="FMP_RATE_LIMIT_COOLDOWN",
                    source_statuses={"fmp": "unavailable"},
                )
            if str(exc) == "FMP_DAILY_LIMIT_REACHED":
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="로컬 FMP 일일 호출 한도에 도달해 단일 종목 데이터 조회를 중단했습니다. 대시보드에서 일일 한도를 조정하거나 다음 날짜에 재시도하세요.",
                    reason_code="FMP_DAILY_LIMIT_REACHED",
                    source_statuses={"fmp": "unavailable"},
                )
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="단일 종목 데이터 조회 중 런타임 오류가 발생했습니다.",
                reason_code="FETCH_FAILED",
                source_statuses={"fmp": "unavailable"},
            )
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="단일 종목 데이터 조회에 실패했고 사용할 stale 캐시도 없습니다.",
                reason_code="FETCH_FAILED",
                source_statuses={"fmp": "unavailable"},
            )

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


def _cache_age_hours(fetched_at: datetime) -> float:
    return max(0.0, (datetime.now(UTC) - fetched_at).total_seconds() / 3600.0)


def _clamp_non_negative(value: float) -> float:
    if value < 0:
        return 0.0
    return value


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default
