# Macro dashboard

An interactive Streamlit dashboard for macroeconomic and commodities data,
with local caching so re-running the dashboard doesn't hit any API every
time.

Tracks GDP, CPI, the unemployment rate, the Fed funds rate, the 10-year
Treasury yield, and M2 money supply from [FRED](https://fred.stlouisfed.org/docs/api/fred/),
plus WTI crude oil, Henry Hub natural gas, and copper from
[Alpha Vantage](https://www.alphavantage.co/documentation/#commodities), out
of the box.

## Setup

```bash
cd fred-macro-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Get two free API keys:

- FRED: https://fred.stlouisfed.org/docs/api/api_key.html
- Alpha Vantage: https://www.alphavantage.co/support/#api-key (free tier is
  25 requests/day — irrelevant in practice since results are cached locally)

Then either export them:

```bash
export FRED_API_KEY=your_key_here
export ALPHA_VANTAGE_API_KEY=your_key_here
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
view (Level / % change / YoY % change), plus a summary panel and one chart
card per selected series.

The first load for a series hits its source API and caches the result to
`data/<SERIES_ID>.csv`. Subsequent runs read from that cache. To force a
fresh pull:

- Click **"Refresh selected"** in the sidebar to refresh just the currently
  selected series, or
- Run `streamlit run app.py -- --refresh` to force-refresh every default
  series on startup, or
- Run the fetch layer standalone (useful for cron/pre-warming the cache):

  ```bash
  python fetch.py --refresh                      # refresh all configured series
  python fetch.py --refresh --series GDP WTI      # refresh specific series
  ```

If an API key is missing or invalid, or a request fails, you'll see a clear
error message (in the sidebar/app or on stderr for the CLI) instead of a
stack trace.

## Adding a new series

Add one entry to `SERIES` in [`config.py`](config.py) — the series ID (as
used by the source) mapped to a friendly label and a source
(`"fred"` or `"alpha_vantage"`):

```python
SERIES = {
    ...,
    "PAYEMS": {"label": "Nonfarm Payrolls", "source": "fred"},
}
```

It'll then show up in the sidebar and can be fetched/cached/plotted like any
other series. Adding a third data source means adding one function to the
`_FETCHERS` dispatch table in [`fetch.py`](fetch.py).

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
├── app.py                # Streamlit entry point (sidebar, charts, summary panel)
├── fetch.py               # FRED + Alpha Vantage calls + CSV caching + CLI --refresh
├── transform.py            # pandas: pct_change / yoy_pct_change / latest_summary
├── config.py                # SERIES registry, cache dir, API base URLs
├── .streamlit/config.toml    # dark financial-dashboard theme
├── data/                      # cached CSVs, one per series (gitignored)
├── tests/
│   └── test_transform.py
├── requirements.txt
├── .env.example
└── .gitignore
```

## Design notes

- **Caching**: one CSV per series under `data/`, keyed by series ID,
  regardless of source. No cache metadata file — "last refreshed" can be
  read from the file's mtime.
- **Multi-source**: each entry in `config.SERIES` carries a `source` tag;
  `fetch.get_series` dispatches to the matching fetcher in `_FETCHERS`. The
  cache, transforms, and UI are all source-agnostic — they only ever see a
  `date`/`value` DataFrame.
- **YoY calculation**: GDP is quarterly, CPI/unemployment/Fed funds/M2/
  commodities are monthly, and the 10-year yield is daily — so YoY change is
  computed by matching each observation against the closest one from ~1 year
  earlier (via `pd.merge_asof`) rather than a fixed row offset, which would
  break across mixed frequencies.
- **Missing observations**: both sources mark missing values with a
  non-numeric placeholder; these are parsed to `NaN` (not dropped), so gaps
  show up as gaps rather than silently shifting dates.
