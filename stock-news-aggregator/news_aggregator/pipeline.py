"""Shared fetch-and-store pipeline, used by both the one-shot `fetch` CLI
command and the recurring scheduler so the logic lives in exactly one place.
"""
from __future__ import annotations

from .config import DB_PATH, NEWSAPI_SOURCES, RSS_SOURCES
from .db import get_connection, insert_news_items
from .fetcher import fetch_all_rss
from .newsapi_source import fetch_all_newsapi


def run_fetch_cycle() -> int:
    """Fetch every configured source once and store new items. Returns count inserted."""
    items = fetch_all_rss(RSS_SOURCES)
    items.extend(fetch_all_newsapi(NEWSAPI_SOURCES))

    conn = get_connection(DB_PATH)
    try:
        inserted = insert_news_items(conn, items)
    finally:
        conn.close()

    duplicates = len(items) - inserted
    print(f"[INFO] Fetch cycle complete: {len(items)} fetched, {inserted} new, {duplicates} duplicate(s) skipped.")
    return inserted
