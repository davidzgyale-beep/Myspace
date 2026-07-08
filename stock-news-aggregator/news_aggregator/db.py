"""SQLite storage: schema, dedup-on-insert, and filtered query helpers."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import NewsItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    link        TEXT NOT NULL UNIQUE,
    published   TEXT NOT NULL,
    source      TEXT NOT NULL,
    summary     TEXT,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
"""


def _regexp(pattern: str, value: Optional[str]) -> bool:
    if value is None:
        return False
    return re.search(pattern, value, re.IGNORECASE) is not None


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, _regexp)
    conn.executescript(SCHEMA)
    return conn


def insert_news_items(conn: sqlite3.Connection, items: list[NewsItem]) -> int:
    """Insert items, skipping any whose link already exists. Returns count actually inserted."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for item in items:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO news (title, link, published, source, summary, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item.title, item.link, item.published, item.source, item.summary, fetched_at),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def query_news(
    conn: sqlite3.Connection,
    keyword: Optional[str] = None,
    ticker: Optional[str] = None,
    source: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[sqlite3.Row]:
    """Filter stored news, newest first.

    keyword: plain substring match (case-insensitive) against title/summary.
    ticker:  word-boundary match (case-insensitive) against title/summary, so
             "AAPL" matches "AAPL", "$AAPL", "(AAPL)", "NASDAQ:AAPL" but not "AAPLE".
    since/until: ISO-8601 timestamps, inclusive/exclusive respectively.
    """
    clauses = []
    params: list = []

    if keyword:
        clauses.append("(title LIKE ? OR summary LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like])

    if ticker:
        pattern = rf"\b{re.escape(ticker)}\b"
        clauses.append("(title REGEXP ? OR summary REGEXP ?)")
        params.extend([pattern, pattern])

    if source:
        clauses.append("source = ?")
        params.append(source)

    if since:
        clauses.append("published >= ?")
        params.append(since)

    if until:
        clauses.append("published < ?")
        params.append(until)

    sql = "SELECT * FROM news"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY published DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    return conn.execute(sql, params).fetchall()
