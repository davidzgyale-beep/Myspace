"""Central configuration: source lists, runtime settings, and env var loading.

Sources are defined as plain dataclasses so adding/removing a feed is a
one-line change here, with no other code to touch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "news.db"

# Optional convenience: load a .env file if python-dotenv happens to be
# installed. Not a hard dependency -- if it's missing we just read
# os.environ directly (export vars yourself, or `set -a; source .env; set +a`).
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

HTTP_TIMEOUT = int(os.environ.get("NEWS_HTTP_TIMEOUT", "15"))

# SEC EDGAR (and some other feeds) require a descriptive User-Agent identifying
# the requester. See https://www.sec.gov/os/webmaster-faq#developers
USER_AGENT = os.environ.get(
    "NEWS_USER_AGENT",
    "stock-news-aggregator/1.0 (set NEWS_USER_AGENT env var to your contact info)",
)

DEFAULT_FETCH_INTERVAL_MINUTES = int(os.environ.get("FETCH_INTERVAL_MINUTES", "15"))

# Reuters and Bloomberg discontinued public RSS feeds. NEWSAPI_KEY enables an
# optional supplemental module (news_aggregator.newsapi_source) that pulls
# their coverage from NewsAPI.org instead. Leave unset to skip cleanly.
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()


@dataclass(frozen=True)
class RSSSource:
    name: str
    url: str


@dataclass(frozen=True)
class NewsAPISource:
    """Pluggable supplemental source backed by NewsAPI.org (or a compatible aggregator)."""

    name: str
    domains: str  # comma-separated domain filter, e.g. "reuters.com"


# ---- Primary sources: all public RSS/Atom feeds, no API key required ----
RSS_SOURCES: list[RSSSource] = [
    RSSSource("CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    RSSSource("CNBC Markets", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    RSSSource("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    RSSSource("MarketWatch Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    RSSSource("MarketWatch Breaking Bulletins", "https://feeds.content.dowjones.io/public/rss/mw_bulletins"),
    RSSSource("WSJ Markets", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
    RSSSource("Yahoo Finance News", "https://finance.yahoo.com/news/rssindex"),
    RSSSource("Financial Times Markets", "https://www.ft.com/markets?format=rss"),
    RSSSource(
        "SEC EDGAR Latest 8-K Filings",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=100&output=atom",
    ),
]

# ---- Optional supplemental sources: only fetched when NEWSAPI_KEY is set ----
NEWSAPI_SOURCES: list[NewsAPISource] = [
    NewsAPISource("Reuters (via NewsAPI)", domains="reuters.com"),
    NewsAPISource("Bloomberg (via NewsAPI)", domains="bloomberg.com"),
]
