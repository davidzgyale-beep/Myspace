"""Fetch and normalize entries from the primary RSS/Atom sources.

Every source is fetched independently. A network error, HTTP error, or
unparseable feed is caught, logged as a warning, and simply yields zero
items for that source -- it never aborts the rest of the run.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable, Optional

import feedparser
import requests

from .config import HTTP_TIMEOUT, USER_AGENT, RSSSource
from .models import NewsItem


def _struct_time_to_iso(struct_time) -> Optional[str]:
    if not struct_time:
        return None
    return datetime.fromtimestamp(time.mktime(struct_time), tz=timezone.utc).isoformat()


def _entry_to_news_item(entry, source_name: str) -> Optional[NewsItem]:
    link = getattr(entry, "link", None)
    if not link:
        return None

    title = getattr(entry, "title", "").strip()
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    published = (
        _struct_time_to_iso(getattr(entry, "published_parsed", None))
        or _struct_time_to_iso(getattr(entry, "updated_parsed", None))
        or datetime.now(timezone.utc).isoformat()
    )

    return NewsItem(
        title=title,
        link=link,
        published=published,
        source=source_name,
        summary=summary.strip(),
    )


def fetch_rss_source(source: RSSSource) -> list[NewsItem]:
    """Fetch a single RSS/Atom source. Never raises -- returns [] on any failure."""
    try:
        resp = requests.get(source.url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] fetch failed for '{source.name}' ({source.url}): {exc}")
        return []

    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        print(f"[WARN] '{source.name}' returned an unparseable feed: {feed.bozo_exception}")
        return []

    items = []
    for entry in feed.entries:
        item = _entry_to_news_item(entry, source.name)
        if item is not None:
            items.append(item)
    return items


def fetch_all_rss(sources: Iterable[RSSSource]) -> list[NewsItem]:
    """Fetch every source sequentially, isolating failures per-source."""
    all_items: list[NewsItem] = []
    for source in sources:
        items = fetch_rss_source(source)
        print(f"[INFO] {source.name}: {len(items)} item(s)")
        all_items.extend(items)
    return all_items
