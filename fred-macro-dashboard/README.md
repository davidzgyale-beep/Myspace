# FRED Macro Dashboard

An interactive Streamlit dashboard for macroeconomic series from the
[FRED API](https://fred.stlouisfed.org/docs/api/fred/), with local caching so
re-running the dashboard doesn't hit the API every time.

Tracks GDP, CPI, the unemployment rate, the Fed funds rate, the 10-year
Treasury yield, and M2 money supply out of the box.

## Setup

```bash
cd fred-macro-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html, then
either export it:

```bash
export FRED_API_KEY=your_key_here
```

or copy `.env.example` to `.env`, fill it in, and install the optional
`python-dotenv` dependency (uncomment it in `requirements.txt`) so `fetch.py`
picks it up automatically.

## Usage

Run the dashboard:

```bash
streamlit run app.py
```

This opens a browser tab with a sidebar to pick series, a date range, and a
view (Level / % Change / YoY % Change), plus a summary panel and one line
chart per selected series.

The first load for a series hits the FRED API and caches the result to
`data/<SERIES_ID>.csv`. Subsequent runs read from that cache. To force a
fresh pull:

- Click **"Refresh selected from FRED"** in the sidebar to refresh just the
  currently selected series, or
- Run `streamlit run app.py -- --refresh` to force-refresh every default
  series on startup, or
- Run the fetch layer standalone (useful for cron/pre-warming the cache):

  ```bash
  python fetch.py --refresh                      # refresh all configured series
  python fetch.py --refresh --series GDP UNRATE   # refresh specific series
  ```

If `FRED_API_KEY` is missing or invalid, or a request fails, you'll see a
clear error message (in the sidebar/app or on stderr for the CLI) instead of
a stack trace.

## Adding a new series

Add one entry to `SERIES` in [`config.py`](config.py) — the series ID (as
used by FRED) mapped to a friendly label:

```python
SERIES = {
    ...,
    "PAYEMS": "Nonfarm Payrolls",
}
```

It'll then show up in the sidebar and can be fetched/cached/plotted like any
other series.

## Testing

```bash
pytest tests/
```

Tests cover `transform.py` only (% change, YoY change across mixed
frequencies and with gaps, latest-value summary) using fixture DataFrames —
no live API calls.

## Project layout

```
fred-macro-dashboard/
├── app.py           # Streamlit entry point (sidebar, charts, summary panel)
├── fetch.py          # FRED API calls + CSV caching + CLI --refresh
├── transform.py       # pandas: pct_change / yoy_pct_change / latest_summary
├── config.py           # SERIES registry, cache dir, API base URL
├── data/                # cached CSVs, one per series (gitignored)
├── tests/
│   └── test_transform.py
├── requirements.txt
├── .env.example
└── .gitignore
```

## Design notes

- **Caching**: one CSV per series under `data/`, keyed by series ID. No
  cache metadata file — "last refreshed" can be read from the file's mtime.
- **YoY calculation**: GDP is quarterly, CPI/unemployment/Fed funds/M2 are
  monthly, and the 10-year yield is daily — so YoY change is computed by
  matching each observation against the closest one from ~1 year earlier
  (via `pd.merge_asof`) rather than a fixed row offset, which would break
  across mixed frequencies.
- **Missing observations**: FRED marks missing values as `"."`; these are
  parsed to `NaN` (not dropped), so gaps show up as gaps rather than
  silently shifting dates.
