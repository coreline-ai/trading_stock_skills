from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


DEFAULT_RSS_FEEDS: dict[str, str] = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "BLS": "https://www.bls.gov/feed/bls_latest.rss",
    "BEA": "https://www.bea.gov/news/rss.xml",
    "U.S. Treasury": "https://home.treasury.gov/news/rss",
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
}


class RSSClient:
    def __init__(self, feeds: dict[str, str] | None = None) -> None:
        self.feeds = feeds or DEFAULT_RSS_FEEDS

    def fetch(self, max_items: int = 80) -> tuple[list[dict[str, Any]], list[str]]:
        items: list[dict[str, Any]] = []
        warnings: list[str] = []

        for source, url in self.feeds.items():
            try:
                req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})
                with urlopen(req, timeout=8) as response:
                    raw = response.read().decode("utf-8", errors="ignore")
                root = ET.fromstring(raw)
            except Exception:
                warnings.append(f"RSS fetch failed: {source}")
                continue

            for item in root.findall(".//item"):
                title = _find_text(item, "title")
                link = _find_text(item, "link")
                pub = _find_text(item, "pubDate")
                items.append(
                    {
                        "headline": title,
                        "source": source,
                        "source_url": link,
                        "published_at": _to_iso(pub),
                    }
                )

        # dedupe by headline+source
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for row in items:
            key = f"{row.get('source')}::{row.get('headline')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_items:
                break

        return deduped, warnings


def _find_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _to_iso(raw: str) -> str:
    if not raw:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.isoformat()
        except ValueError:
            continue
    return raw
