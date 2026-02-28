from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class MarketNewsAnalyzer(SkillAnalyzer):
    slug = "market-news-analyst"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        lookback_days = _to_int(params.get("lookback_days"), 10)
        max_items = _to_int(params.get("max_items"), 80)

        start = context.as_of_date - timedelta(days=max(1, lookback_days))
        cache_key = _cache_key(self.slug, {"start": start.isoformat(), "max_items": max_items})

        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            source_states = cached.payload.get("_source_states", {}) if isinstance(cached.payload, dict) else {}
            fmp_state = str(source_states.get("fmp", "live"))
            rss_state = str(source_states.get("rss", "live"))
            if context.fmp_news is None and fmp_state == "live":
                fmp_state = "unavailable"
            if not (context.fmp_news is not None and fmp_state != "live"):
                return self._build_ok(cached.payload, CacheStore.cache_info("fresh", cached), fmp_state, rss_state)

        rss_news, rss_warnings = _safe_fetch_rss(context=context, max_items=max_items)
        context.warnings.extend(rss_warnings)

        if context.fmp_news is None:
            payload = self._compose_payload(fmp_news=[], rss_news=rss_news, max_items=max_items)
            if payload["ranked_events"]:
                rss_state = "live" if rss_news else "unavailable"
                cached_payload = _with_source_states(payload, fmp_state="unavailable", rss_state=rss_state)
                saved = context.cache_store.set(cache_key, cached_payload, ttl_hours=6)
                return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "unavailable", rss_state)

            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY_AND_EMPTY_RSS -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "unavailable", "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="FMP API 키가 없고 RSS 데이터도 없어 뉴스 분석을 수행할 수 없습니다.",
                reason_code="NO_API_KEY_AND_EMPTY_RSS",
                source_statuses={"fmp": "unavailable", "rss": "unavailable"},
            )

        try:
            fmp_news = context.fmp_news.get_market_news(limit=max_items)

            payload = self._compose_payload(fmp_news=fmp_news, rss_news=rss_news, max_items=max_items)
            if not payload["ranked_events"]:
                stale = context.cache_store.get_stale(cache_key)
                if stale:
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale", "stale")
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="뉴스 소스가 비어 있어 분석할 수 없습니다.",
                    reason_code="EMPTY_SOURCE",
                    source_statuses={"fmp": "unavailable", "rss": "unavailable"},
                )

            rss_state = "live" if rss_news else "unavailable"
            cached_payload = _with_source_states(payload, fmp_state="live", rss_state=rss_state)
            saved = context.cache_store.set(cache_key, cached_payload, ttl_hours=6)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live", rss_state)
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale", "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="뉴스 수집/분석에 실패했습니다.",
                reason_code="FETCH_FAILED",
                source_statuses={"fmp": "unavailable", "rss": "unavailable"},
            )

    def _compose_payload(
        self,
        fmp_news: list[dict[str, Any]],
        rss_news: list[dict[str, Any]],
        max_items: int,
    ) -> dict[str, Any]:
        merged: list[dict[str, Any]] = []

        for item in fmp_news:
            headline = str(item.get("title") or "").strip()
            if not headline:
                continue
            merged.append(
                {
                    "headline": headline,
                    "published_at": str(item.get("publishedDate") or ""),
                    "source": str(item.get("site") or "FMP"),
                    "source_url": str(item.get("url") or "https://financialmodelingprep.com"),
                }
            )

        merged.extend(rss_news)

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in merged:
            key = row["headline"].lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_items:
                break

        ranked = []
        clusters: dict[str, int] = {}
        for row in deduped:
            p, b, f = _score_dimensions(row["headline"])
            impact = round((p * b) * f, 2)
            cluster = _cluster(row["headline"])
            clusters[cluster] = clusters.get(cluster, 0) + 1
            ranked.append(
                {
                    "headline": row["headline"],
                    "published_at": row["published_at"],
                    "source": row["source"],
                    "price_impact": p,
                    "breadth": b,
                    "forward_significance": f,
                    "impact_score": impact,
                    "source_url": row["source_url"],
                    "related_tickers": _extract_tickers(row["headline"]),
                }
            )

        ranked.sort(key=lambda x: x["impact_score"], reverse=True)
        return {"ranked_events": ranked[:60], "theme_clusters": clusters}

    def _build_ok(
        self,
        payload: dict[str, Any],
        cache_info: dict[str, str | None],
        fmp_state: str,
        rss_state: str,
    ) -> SkillRunResultV2:
        ranked_events = payload.get("ranked_events", [])
        source_payload = dict(payload)
        source_payload["_source_states"] = {"fmp": fmp_state, "rss": rss_state}
        avg_impact = sum(item.get("impact_score", 0) for item in ranked_events[:10]) / max(1, min(10, len(ranked_events)))
        score = min(100.0, 45 + avg_impact * 8)
        confidence = min(0.95, 0.5 + min(0.4, len(ranked_events) / 120))

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"FMP/RSS 뉴스 {len(ranked_events)}건을 임팩트 스코어로 랭킹했습니다.",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=source_payload,
            source_statuses={"fmp": fmp_state, "rss": rss_state},
        )


def _safe_fetch_rss(context: AnalyzerContext, max_items: int) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return context.rss_client.fetch(max_items=max_items)
    except Exception:
        return [], ["RSS fetch failed: internal error"]


def _with_source_states(payload: dict[str, Any], fmp_state: str, rss_state: str) -> dict[str, Any]:
    copied = dict(payload)
    copied["_source_states"] = {"fmp": fmp_state, "rss": rss_state}
    return copied


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"


def _score_dimensions(headline: str) -> tuple[float, float, float]:
    text = headline.lower()
    price = 0.8
    breadth = 0.8
    forward = 0.8

    if any(k in text for k in ["fed", "fomc", "rate", "inflation", "cpi", "nfp"]):
        price += 0.6
        breadth += 0.7
        forward += 0.5
    if any(k in text for k in ["earnings", "guidance", "revenue", "eps"]):
        price += 0.5
        forward += 0.4
    if any(k in text for k in ["war", "sanction", "tariff", "geopolitical"]):
        breadth += 0.6
        forward += 0.5

    return round(min(price, 2.5), 2), round(min(breadth, 2.5), 2), round(min(forward, 2.5), 2)


def _cluster(headline: str) -> str:
    text = headline.lower()
    if any(k in text for k in ["fed", "cpi", "inflation", "rate", "yield"]):
        return "macro"
    if any(k in text for k in ["earnings", "guidance", "eps", "revenue"]):
        return "earnings"
    if any(k in text for k in ["oil", "energy", "commodity"]):
        return "commodities"
    if any(k in text for k in ["war", "sanction", "tariff", "election"]):
        return "geopolitics"
    return "general"


def _extract_tickers(headline: str) -> list[str]:
    candidates: list[str] = []
    tokens = headline.replace("/", " ").replace("-", " ").split()
    for token in tokens:
        clean = token.strip("(),.:;")
        if clean.isupper() and 1 < len(clean) <= 5 and clean.isalpha():
            candidates.append(clean)
    return candidates[:3]
