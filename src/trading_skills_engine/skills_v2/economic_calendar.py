from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer
from trading_skills_engine.skills_v2.contracts import CacheInfo, SkillRunResultV2


class EconomicCalendarAnalyzer(SkillAnalyzer):
    slug = "economic-calendar-fetcher"

    def run(self, params: dict[str, Any], context: AnalyzerContext) -> SkillRunResultV2:
        from_days = _to_int(params.get("from_days"), 7)
        to_days = _to_int(params.get("to_days"), 90)
        country = str(params.get("country") or "US")

        start = context.as_of_date + timedelta(days=max(0, from_days))
        end = context.as_of_date + timedelta(days=max(1, to_days))

        cache_key = _cache_key(self.slug, {"start": start.isoformat(), "end": end.isoformat(), "country": country})
        cached = context.cache_store.get_fresh(cache_key)
        if cached:
            payload = cached.payload
            if isinstance(payload, dict):
                fmp_state = str(payload.get("_source_state") or "stale")
            else:
                fmp_state = "stale"
            if fmp_state == "live" and context.fmp_calendar is None:
                fmp_state = "stale"
            if not (context.fmp_calendar is not None and fmp_state != "live"):
                return self._build_ok(payload, CacheStore.cache_info("fresh", cached), fmp_state, "unavailable")

        if context.fmp_calendar is None:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale", "stale")

            proxy_payload, rss_state, warnings = self._build_proxy_payload(context=context, start=start, end=end, country=country)
            context.warnings.extend(warnings)
            saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=12)
            return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "stale", rss_state)

        try:
            raw = context.fmp_calendar.get_economic_calendar(start=start, end=end, country=country)
            if not raw:
                stale = context.cache_store.get_stale(cache_key)
                if stale and _source_state(stale.payload) == "live":
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale", "stale")
                proxy_payload, rss_state, warnings = self._build_proxy_payload(
                    context=context,
                    start=start,
                    end=end,
                    country=country,
                )
                context.warnings.extend(warnings)
                context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> proxy 사용")
                saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=12)
                return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "unavailable", rss_state)
            payload = self._parse_events(raw)
            payload["_source_state"] = "live"
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live", "unavailable")
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale and _source_state(stale.payload) == "live":
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale", "stale")
            proxy_payload, rss_state, warnings = self._build_proxy_payload(
                context=context,
                start=start,
                end=end,
                country=country,
            )
            context.warnings.extend(warnings)
            context.warnings.append(f"{self.slug}: FETCH_FAILED -> proxy 사용")
            saved = context.cache_store.set(cache_key, proxy_payload, ttl_hours=12)
            return self._build_ok(proxy_payload, CacheStore.cache_info("fresh", saved), "unavailable", rss_state)

    def _parse_events(self, raw: list[dict[str, Any]]) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        high = med = low = 0
        for item in raw[:300]:
            impact = _norm_impact(item.get("impact"))
            if impact == "High":
                high += 1
            elif impact == "Medium":
                med += 1
            else:
                low += 1

            events.append(
                {
                    "datetime": str(item.get("date") or item.get("datetime") or ""),
                    "event": str(item.get("event") or item.get("title") or ""),
                    "impact": impact,
                    "consensus": str(item.get("estimate") or ""),
                    "previous": str(item.get("previous") or ""),
                    "source_url": str(item.get("url") or "https://financialmodelingprep.com"),
                }
            )

        return {
            "events": events,
            "impact_summary": {"High": high, "Medium": med, "Low": low},
        }

    def _build_proxy_payload(
        self,
        context: AnalyzerContext,
        start: Any,
        end: Any,
        country: str,
    ) -> tuple[dict[str, Any], str, list[str]]:
        warnings: list[str] = []
        events: list[dict[str, Any]] = []

        try:
            rss_rows, rss_warnings = context.rss_client.fetch(max_items=24)
            warnings.extend(rss_warnings)
        except Exception:
            rss_rows = []
            warnings.append(f"{self.slug}: RSS fetch failed -> template proxy")

        for row in rss_rows[:16]:
            headline = str(row.get("headline") or "").strip()
            if not headline:
                continue
            events.append(
                {
                    "datetime": str(row.get("published_at") or start.isoformat()),
                    "event": headline,
                    "impact": _impact_from_headline(headline),
                    "consensus": "",
                    "previous": "",
                    "source_url": str(row.get("source_url") or ""),
                }
            )

        if not events:
            template_names = [
                "US CPI",
                "US PPI",
                "FOMC Statement",
                "US Nonfarm Payrolls",
                "US Retail Sales",
                "US ISM PMI",
            ]
            cursor = start
            for idx, name in enumerate(template_names):
                cursor = cursor + timedelta(days=max(1, idx * 3 + 1))
                if cursor > end:
                    break
                events.append(
                    {
                        "datetime": cursor.isoformat(),
                        "event": f"{country} {name}",
                        "impact": "High" if idx < 3 else "Medium",
                        "consensus": "",
                        "previous": "",
                        "source_url": "",
                    }
                )
            mode = "template_proxy"
            rss_state = "stale"
        else:
            mode = "rss_proxy"
            rss_state = "live"

        summary = Counter(item.get("impact", "Low") for item in events)
        payload = {
            "mode": mode,
            "events": events,
            "impact_summary": {
                "High": int(summary.get("High", 0)),
                "Medium": int(summary.get("Medium", 0)),
                "Low": int(summary.get("Low", 0)),
            },
            "_source_state": "stale",
        }
        return payload, rss_state, warnings

    def _build_ok(
        self,
        payload: dict[str, Any],
        cache_info: dict[str, str | None],
        fmp_state: str,
        rss_state: str,
    ) -> SkillRunResultV2:
        summary = payload.get("impact_summary", {})
        high = int(summary.get("High", 0))
        med = int(summary.get("Medium", 0))
        low = int(summary.get("Low", 0))

        score = min(100.0, 45.0 + high * 4 + med * 1.5)
        confidence = min(0.95, 0.55 + min(0.35, (high + med) / 200))

        return SkillRunResultV2(
            skill_slug=self.slug,
            status="ok",
            score_0_100=round(score, 2),
            confidence_0_1=round(confidence, 2),
            summary_ko=f"향후 이벤트 {len(payload.get('events', []))}건(High {high}, Medium {med}, Low {low})을 분석했습니다.",
            cache_info=CacheInfo(**cache_info),
            analysis_payload=payload,
            source_statuses={"fmp": fmp_state, "rss": rss_state},
        )


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _norm_impact(raw: Any) -> str:
    text = str(raw or "").lower()
    if "high" in text:
        return "High"
    if "med" in text:
        return "Medium"
    if "low" in text:
        return "Low"
    return "Low"


def _cache_key(slug: str, params: dict[str, Any]) -> str:
    return f"{slug}:{sha256(json.dumps(params, sort_keys=True).encode('utf-8')).hexdigest()}"


def _impact_from_headline(headline: str) -> str:
    text = headline.lower()
    if any(key in text for key in ["fed", "fomc", "cpi", "inflation", "payroll", "rate"]):
        return "High"
    if any(key in text for key in ["gdp", "pmi", "retail", "yield"]):
        return "Medium"
    return "Low"


def _source_state(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("_source_state") or "stale")
    return "stale"
