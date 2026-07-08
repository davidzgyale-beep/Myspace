"""Optional supplemental source: Reuters/Bloomberg via NewsAPI.org.

Reuters and Bloomberg both discontinued their public RSS feeds, so this
module fills the gap through NewsAPI (https://newsapi.org) instead. It only
activates when the NEWSAPI_KEY environment variable is set; when it's not,
every function here is a silent no-op so the rest of the pipeline runs
cleanly without an API key.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

import requests

from .config import HTTP_TIMEOUT, NEWSAPI_KEY, NewsAPISource
from .models import NewsItem

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


def fetch_newsapi_source(source: NewsAPISource, query: Optional[str] = None) -> list[NewsItem]:
    """Fetch one supplemental source. Returns [] if no API key is set or on any error."""
    if not NEWSAPI_KEY:
        return []

    params = {
        "domains": source.domains,
        "sortBy": "publishedAt",
        "pageSize": 50,
        "apiKey": NEWSAPI_KEY,
    }
    if query:
        params["q"] = query

    try:
        resp = requests.get(NEWSAPI_ENDPOINT, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[WARN] NewsAPI fetch failed for '{source.name}': {exc}")
        return []

    if payload.get("status") != "ok":
        print(f"[WARN] NewsAPI error for '{source.name}': {payload.get('message')}")
        return []

    items = []
    for article in payload.get("articles", []):
        link = article.get("url")
        if not link:
            continue
        published = article.get("publishedAt") or datetime.now(timezone.utc).isoformat()
        items.append(
            NewsItem(
                title=(article.get("title") or "").strip(),
                link=link,
                published=published,
                source=source.name,
                summary=(article.get("description") or "").strip(),
            )
        )
    return items


def fetch_all_newsapi(sources: Iterable[NewsAPISource], query: Optional[str] = None) -> list[NewsItem]:
    """Fetch every supplemental source. Prints one informational skip notice, not an error."""
    if not NEWSAPI_KEY:
        print("[INFO] NEWSAPI_KEY not set -- skipping Reuters/Bloomberg supplemental sources.")
        return []

    all_items: list[NewsItem] = []
    for source in sources:
        items = fetch_newsapi_source(source, query=query)
        print(f"[INFO] {source.name}: {len(items)} item(s)")
        all_items.extend(items)
    return all_items
