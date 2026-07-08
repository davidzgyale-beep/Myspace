# Stock News Aggregator

A lightweight Python news aggregator for stock market headlines. Pulls RSS/Atom
feeds from CNBC, MarketWatch, WSJ, Yahoo Finance, Financial Times, and SEC
EDGAR's live 8-K filing feed; de-dupes by URL into SQLite; and can filter by
keyword/ticker or generate a daily Markdown report.

Built with the standard library plus `feedparser`, `requests`, and `schedule`
-- no heavy framework required.

## Setup

```bash
cd stock-news-aggregator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # optional, edit as needed
```

Environment variables (all optional, see `.env.example`):

| Variable | Purpose | Default |
|---|---|---|
| `NEWS_USER_AGENT` | Sent on every HTTP request; SEC EDGAR requires a descriptive UA | generic placeholder |
| `NEWSAPI_KEY` | Enables the Reuters/Bloomberg supplemental module (see below) | unset -> module skipped |
| `NEWS_HTTP_TIMEOUT` | Per-request timeout in seconds | 15 |
| `FETCH_INTERVAL_MINUTES` | Default interval for `run` | 15 |

If you install `python-dotenv`, `.env` is loaded automatically. Otherwise,
export the variables yourself before running (`set -a; source .env; set +a`).

## Usage

All commands go through `run.py`:

```bash
# Fetch every configured source once and store new items in SQLite
python run.py fetch

# List stored news, optionally filtered
python run.py list --ticker AAPL
python run.py list --keyword "Fed rate"
python run.py list --source "CNBC Markets" --limit 20

# Generate today's Markdown daily report (grouped by source, newest first).
# It leads with a ranked "Top N Market Headlines" section before the
# per-source breakdown -- see below.
python run.py report
python run.py report --date 2026-07-08 --top-n 5

# Print just the ranked top N headlines for a date, without a full report
python run.py top --date 2026-07-08 --n 5

# Run fetch on a recurring schedule (foreground process, Ctrl+C to stop)
python run.py run --interval 15
```

Reports are written to `reports/report-YYYY-MM-DD.md`. The SQLite database
lives at `data/news.db`.

### Top N market headlines

There's no engagement/click data in an RSS feed, so "top" news is a
transparent heuristic, computed in
[`news_aggregator/ranking.py`](news_aggregator/ranking.py):

- stories mentioning market-moving keywords (Fed, earnings, M&A, rate cuts,
  crashes/rallies, etc. -- see `MARKET_KEYWORDS`) score higher
- stories reported by **multiple sources** (the same event covered by, say,
  both CNBC and MarketWatch) score higher -- cross-source pickup is a
  reasonable proxy for how big a story is; titles are clustered with
  `difflib.SequenceMatcher`, no ML/NLP dependency needed
- ties are broken by recency

This ranking layer runs automatically after `report` builds the day's article
list, and is also available standalone via `run.py top`.

### Automating fetches

For unattended use, prefer cron over leaving `run.py run` in a terminal --
see [`crontab.example`](crontab.example) for ready-to-edit entries that fetch
every 15 minutes and generate a report shortly after midnight UTC.

## Data sources

RSS/Atom feeds (no API key needed), defined in
[`news_aggregator/config.py`](news_aggregator/config.py):

- CNBC: Top News, Markets, Finance
- MarketWatch: Top Stories, Breaking Bulletins
- WSJ: Markets
- Yahoo Finance News
- Financial Times: Markets
- SEC EDGAR: latest 8-K filings (Atom feed)

### Reuters / Bloomberg (optional)

Both discontinued their public RSS feeds. [`news_aggregator/newsapi_source.py`](news_aggregator/newsapi_source.py)
provides a pluggable module that fetches their coverage from
[NewsAPI.org](https://newsapi.org) when `NEWSAPI_KEY` is set. With no key
configured, `fetch` simply logs an informational skip notice and continues --
it never errors or aborts the run. Swap in a different aggregator by editing
`NEWSAPI_ENDPOINT`/`fetch_newsapi_source` or adding a new module alongside it;
`pipeline.py` is the only place that wires sources together.

## Design notes

- **Fault isolation**: `fetcher.fetch_rss_source()` and
  `newsapi_source.fetch_newsapi_source()` each catch their own network/parse
  errors, print a `[WARN]` line, and return an empty list -- one broken feed
  never takes down the rest of the run.
- **Dedup**: `news.link` has a `UNIQUE` constraint; inserts use
  `INSERT OR IGNORE`, so re-fetching the same feed is a no-op for articles
  already stored.
- **Ticker matching**: `--ticker AAPL` uses a word-boundary regex (via a
  SQLite `REGEXP` function backed by Python's `re`), so it matches `AAPL`,
  `$AAPL`, `(AAPL)`, `NASDAQ:AAPL`, but not `AAPLESAUCE`.

## Project layout

```
stock-news-aggregator/
├── run.py                       # entry point: python run.py <command>
├── news_aggregator/
│   ├── config.py                 # source list + env var settings
│   ├── models.py                 # NewsItem dataclass
│   ├── fetcher.py                # RSS/Atom fetch + parse, per-source error isolation
│   ├── newsapi_source.py         # optional Reuters/Bloomberg via NewsAPI.org
│   ├── db.py                     # SQLite schema, insert-with-dedup, filtered queries
│   ├── pipeline.py                # shared fetch-all-and-store cycle
│   ├── ranking.py                 # top-N headline ranking (keywords + cross-source coverage)
│   ├── report.py                  # Markdown daily report generator (embeds the top-N section)
│   ├── scheduler.py               # `schedule`-based recurring fetch loop
│   └── cli.py                     # argparse command-line interface
├── data/news.db                  # SQLite database (created on first fetch)
├── reports/report-*.md           # generated daily reports
├── crontab.example
├── requirements.txt
└── .env.example
```

## Database schema

```sql
CREATE TABLE news (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    link        TEXT NOT NULL UNIQUE,   -- dedup key
    published   TEXT NOT NULL,          -- ISO-8601 UTC, from the feed
    source      TEXT NOT NULL,          -- e.g. "CNBC Markets"
    summary     TEXT,
    fetched_at  TEXT NOT NULL           -- ISO-8601 UTC, when we pulled it
);
```
