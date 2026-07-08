"""Generate a Markdown daily report of stored news, grouped by source."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import REPORTS_DIR
from .db import query_news
from .ranking import format_top_stories_markdown, rank_top_stories


def day_bounds_utc(date_str: str) -> tuple[str, str]:
    start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def generate_daily_report(
    conn: sqlite3.Connection, date_str: Optional[str] = None, top_n: int = 5
) -> tuple[str, Path]:
    """Build and save the Markdown report for the given date (YYYY-MM-DD, default today, UTC).

    The report leads with a ranked "Top N Market Headlines" section (see
    ranking.rank_top_stories), followed by the full per-source breakdown.

    Returns (markdown_text, path_written_to).
    """
    date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since, until = day_bounds_utc(date_str)
    rows = query_news(conn, since=since, until=until)

    # Group by source, preserving the newest-first order already applied by query_news.
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(row["source"], []).append(row)

    # Source sections are ordered by their own most recent article, latest first.
    ordered_sources = sorted(groups, key=lambda s: groups[s][0]["published"], reverse=True)

    lines = [
        f"# Stock News Daily Report — {date_str} (UTC)",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"Total articles: {len(rows)}",
        "",
    ]

    # Top-N layer: ranks the day's stories by market-relevance keywords and
    # cross-source coverage, then renders ahead of the full per-source listing.
    top_stories = rank_top_stories(rows, top_n=top_n)
    lines.extend(format_top_stories_markdown(top_stories, heading=f"Top {top_n} Market Headlines"))
    lines.append("---")
    lines.append("")

    if not rows:
        lines.append("_No articles found for this date._")
    else:
        for source in ordered_sources:
            articles = groups[source]
            lines.append(f"## {source} ({len(articles)})")
            lines.append("")
            for row in articles:
                lines.append(f"### {row['title'] or '(untitled)'}")
                lines.append(f"- **Published:** {row['published']}")
                lines.append(f"- **Link:** {row['link']}")
                if row["summary"]:
                    lines.append(f"- **Summary:** {row['summary']}")
                lines.append("")
            lines.append("---")
            lines.append("")

    content = "\n".join(lines)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"report-{date_str}.md"
    out_path.write_text(content, encoding="utf-8")
    return content, out_path
