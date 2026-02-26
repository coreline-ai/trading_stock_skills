from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from typing import Any

from trading_skills_engine.data.cache_store import CacheStore
from trading_skills_engine.skills_v2.base import AnalyzerContext, SkillAnalyzer, unavailable_result
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
            return self._build_ok(payload, CacheStore.cache_info("fresh", cached), "live")

        if context.fmp_calendar is None:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: NO_API_KEY -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="FMP API 키가 없어 경제 캘린더를 조회할 수 없습니다.",
                reason_code="NO_API_KEY",
                source_statuses={"fmp": "unavailable"},
            )

        try:
            raw = context.fmp_calendar.get_economic_calendar(start=start, end=end, country=country)
            if not raw:
                stale = context.cache_store.get_stale(cache_key)
                if stale:
                    context.warnings.append(f"{self.slug}: EMPTY_SOURCE -> stale cache 사용")
                    return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
                return unavailable_result(
                    skill_slug=self.slug,
                    summary_ko="경제 캘린더 소스가 비어 있어 분석할 수 없습니다.",
                    reason_code="EMPTY_SOURCE",
                    source_statuses={"fmp": "unavailable"},
                )
            payload = self._parse_events(raw)
            saved = context.cache_store.set(cache_key, payload, ttl_hours=24)
            return self._build_ok(payload, CacheStore.cache_info("fresh", saved), "live")
        except Exception:
            stale = context.cache_store.get_stale(cache_key)
            if stale:
                context.warnings.append(f"{self.slug}: FETCH_FAILED -> stale cache 사용")
                return self._build_ok(stale.payload, CacheStore.cache_info("stale", stale), "stale")
            return unavailable_result(
                skill_slug=self.slug,
                summary_ko="경제 캘린더 조회에 실패했습니다.",
                reason_code="FETCH_FAILED",
                source_statuses={"fmp": "unavailable"},
            )

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

    def _build_ok(self, payload: dict[str, Any], cache_info: dict[str, str | None], fmp_state: str) -> SkillRunResultV2:
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
            source_statuses={"fmp": fmp_state},
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
