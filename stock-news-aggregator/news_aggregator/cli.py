"""Command-line interface for the stock news aggregator.

Commands:
    fetch   - run one fetch cycle across all sources and store new items
    list    - query stored news, optionally filtered by --keyword / --ticker / --source
    report  - generate a Markdown daily report (default: today, UTC)
    top     - print the ranked top N market headlines for a date (no full report)
    run     - run fetch on a recurring schedule (foreground, uses `schedule`)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .config import DB_PATH, DEFAULT_FETCH_INTERVAL_MINUTES
from .db import get_connection, query_news
from .pipeline import run_fetch_cycle
from .ranking import rank_top_stories
from .report import day_bounds_utc, generate_daily_report
from .scheduler import run_forever


def _cmd_fetch(args: argparse.Namespace) -> None:
    run_fetch_cycle()


def _cmd_list(args: argparse.Namespace) -> None:
    conn = get_connection(DB_PATH)
    try:
        rows = query_news(
            conn,
            keyword=args.keyword,
            ticker=args.ticker,
            source=args.source,
            limit=args.limit,
        )
    finally:
        conn.close()

    if not rows:
        print("No matching news found.")
        return

    for row in rows:
        print(f"[{row['published']}] ({row['source']}) {row['title']}")
        print(f"    {row['link']}")
    print(f"\n{len(rows)} article(s) matched.")


def _cmd_report(args: argparse.Namespace) -> None:
    conn = get_connection(DB_PATH)
    try:
        _, path = generate_daily_report(conn, date_str=args.date, top_n=args.top_n)
    finally:
        conn.close()
    print(f"[INFO] Report written to {path}")


def _cmd_top(args: argparse.Namespace) -> None:
    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    since, until = day_bounds_utc(date_str)

    conn = get_connection(DB_PATH)
    try:
        rows = query_news(conn, since=since, until=until)
    finally:
        conn.close()

    stories = rank_top_stories(rows, top_n=args.n)
    if not stories:
        print(f"No stored news for {date_str} to rank.")
        return

    print(f"Top {len(stories)} market headlines for {date_str} (UTC):\n")
    for rank, story in enumerate(stories, start=1):
        print(f"{rank}. {story.title}  (score: {story.score})")
        sources = story.source if not story.other_sources else f"{story.source}, {', '.join(story.other_sources)}"
        print(f"   Sources: {sources}")
        print(f"   {story.link}")
        print()


def _cmd_run(args: argparse.Namespace) -> None:
    run_forever(interval_minutes=args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="news_aggregator",
        description="Stock market news aggregator: fetch RSS feeds, store in SQLite, "
        "filter by keyword/ticker, and generate daily Markdown reports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch all sources once and store new items.")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_list = sub.add_parser("list", help="Query stored news with optional filters.")
    p_list.add_argument("--keyword", help='Filter by keyword, e.g. "Fed rate"')
    p_list.add_argument("--ticker", help="Filter by stock ticker, e.g. AAPL")
    p_list.add_argument("--source", help="Filter by exact source name")
    p_list.add_argument("--limit", type=int, default=50, help="Max results (default 50)")
    p_list.set_defaults(func=_cmd_list)

    p_report = sub.add_parser("report", help="Generate a Markdown daily report.")
    p_report.add_argument("--date", help="Date in YYYY-MM-DD (default: today, UTC)")
    p_report.add_argument("--top-n", type=int, default=5, help="Headlines in the top section (default 5)")
    p_report.set_defaults(func=_cmd_report)

    p_top = sub.add_parser(
        "top", help="Print the ranked top N market headlines for a date, without a full report."
    )
    p_top.add_argument("--date", help="Date in YYYY-MM-DD (default: today, UTC)")
    p_top.add_argument("--n", type=int, default=5, help="Number of headlines (default 5)")
    p_top.set_defaults(func=_cmd_top)

    p_run = sub.add_parser("run", help="Run fetch on a recurring schedule (foreground).")
    p_run.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_FETCH_INTERVAL_MINUTES,
        help=f"Minutes between fetches (default {DEFAULT_FETCH_INTERVAL_MINUTES})",
    )
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
