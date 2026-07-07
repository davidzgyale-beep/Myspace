# edgar-financial-exporter

Fetch U.S. public company financial data directly from the **SEC EDGAR / data.sec.gov**
XBRL Company Facts API and export it into a clean, standardized Excel workbook —
no third-party or paid financial-data APIs involved.

## Features

- Look up a company by **ticker** (e.g. `AAPL`) or **CIK** (e.g. `0000320193` / `320193`).
- Pulls the full XBRL "company facts" dataset (`us-gaap` + `dei` taxonomies) for the company.
- Builds three standardized financial statements with a **fixed line-item schema**
  (not a dump of every raw XBRL tag), using fallback tags when a company reports
  under a non-primary XBRL concept.
- Supports both **annual** (`10-K`) and **quarterly** (`10-Q`) modes.
- Restricts output to a **fiscal year range** (`--start-year` / `--end-year`).
- Excel workbook always contains:
  - `Income Statement`
  - `Balance Sheet`
  - `Cash Flow Statement`
  - `Raw Facts` — the cleaned, de-duplicated facts feeding the statements above
  - `Metadata` — company/run metadata
  - `Data Quality Check` — four stacked sections:
    1. per line-item/period status (OK / fallback used / missing), including source
       tag, unit, filing date, and accession number
    2. a summary roll-up (counts and % missing)
    3. **Reconciliation Checks** — cross-statement ties that should always hold exactly
       (Assets = Liabilities + Equity, Net Income agreeing between the Income
       Statement and Cash Flow Statement, Cash at End of Period agreeing with the
       Balance Sheet's cash balance, Net Change in Cash agreeing with the period-over-
       period change in cash); a `Mismatch` here is a strong signal of a tag-mapping bug
    4. **Anomaly Flags** — line items with a >=50% period-over-period swing or a
       sign flip (quarterly comparisons are year-over-year, same quarter, to avoid
       flagging ordinary seasonality) — not necessarily wrong, but worth a glance
  - On the statement sheets themselves, cells are **shaded** yellow (fallback tag
    used) or red (missing) so data quality is visible at a glance, with a small
    legend printed to the right of each table
- Respects SEC's access policy: a configrable **User-Agent**, request **rate limiting**
  (default 8 req/s), on-disk **response caching**, and retry/backoff on `429`/`5xx`.
- Readable error handling for unknown tickers, malformed CIKs, and SEC `403`/`404`/`429`
  responses.

## Project Layout

```
edgar-financial-exporter/
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ outputs/                 # generated .xlsx files land here by default
├─ data/cache/               # on-disk HTTP response cache
├─ src/edgar_exporter/
│  ├─ cli.py                 # Typer CLI entry point (`edgar-export`)
│  ├─ config.py               # .env loading + validation
│  ├─ sec_client.py           # HTTP client: headers, cache, rate limit, retries
│  ├─ cik_lookup.py           # ticker <-> CIK resolution
│  ├─ company_facts.py        # companyfacts JSON fetch + flatten to DataFrame
│  ├─ fact_filter.py          # annual/quarterly filtering, unit rules, de-dup
│  ├─ statement_mappings.py   # standard line item -> XBRL tag (+fallback) mapping
│  ├─ statement_builder.py    # build wide statement tables + quality rows
│  ├─ excel_writer.py         # pandas/openpyxl workbook rendering & formatting
│  ├─ data_quality.py         # combine/summarize the Data Quality Check sheet
│  └─ utils.py                # logging setup
└─ tests/
```

## Installation

Requires Python 3.9+.

```bash
cd edgar-financial-exporter
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

For running the test suite, also install the dev extra:

```bash
pip install -e ".[dev]"
```

## Configuration

SEC requires every request to `data.sec.gov` / `www.sec.gov` to carry a descriptive
`User-Agent` header identifying the requester (see SEC's
[developer FAQ](https://www.sec.gov/os/webmaster-faq#developers)). This tool refuses
to run without one.

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Required
SEC_USER_AGENT="Your Name your.email@example.com"

# Optional (defaults shown)
EDGAR_CACHE_DIR=data/cache
EDGAR_RATE_LIMIT=8
```

## Usage

```bash
# Ticker, annual, explicit year range, explicit output path
edgar-export AAPL --period annual --start-year 2020 --end-year 2025 --output outputs/AAPL_financials.xlsx

# Ticker, quarterly
edgar-export MSFT --period quarterly --start-year 2022 --end-year 2025

# CIK instead of ticker (10-digit or unpadded both work)
edgar-export 0000320193 --period annual
```

### CLI options

| Option | Description | Default |
|---|---|---|
| `ticker_or_cik` (positional) | Ticker symbol or CIK | required |
| `--period` | `annual` or `quarterly` | `annual` |
| `--start-year` | First fiscal year to include | `end_year - 5` |
| `--end-year` | Last fiscal year to include | current year |
| `--output` | Output `.xlsx` path | `outputs/<TICKER>_<period>_<start>_<end>.xlsx` |
| `--no-cache` | Bypass the local response cache | off |
| `--verbose` | Debug-level logging | off |

## Standard line items

The exact, current list always lives in [`statement_mappings.py`](src/edgar_exporter/statement_mappings.py);
this is a snapshot of what each statement sheet contains today.

**Income Statement**: Revenue, Cost of Revenue, Gross Profit, Research and
Development, Selling General and Administrative, Operating Expenses,
Restructuring Charges, Asset Impairment Charges, Goodwill Impairment,
Operating Income, Interest Expense, Total Other Income (Expense) Net, Income
Before Tax, Income Tax Expense, Effective Tax Rate, Net Income, EPS Basic,
EPS Diluted, Weighted Average Shares Basic, Weighted Average Shares Diluted.

**Balance Sheet**: Cash and Cash Equivalents, Short Term Investments, Accounts
Receivable, Inventory, Other Current Assets, Current Assets, Property Plant
and Equipment, Goodwill, Intangible Assets, Other Non-Current Assets,
Non-Current Assets, Total Assets, Accounts Payable, Deferred Revenue
(Current), Other Current Liabilities, Current Liabilities, Long Term Debt,
Deferred Revenue (Non-Current), Other Non-Current Liabilities, Non-Current
Liabilities, Total Liabilities, Common Stock, Additional Paid-in Capital,
Treasury Stock, Retained Earnings, Accumulated Other Comprehensive Income
(Loss), Total Stockholders Equity, Total Liabilities and Equity, Common
Shares Outstanding.

**Cash Flow Statement**: Net Income, Depreciation and Amortization,
Amortization of Intangible Assets, Stock Based Compensation, Deferred Income
Taxes, Goodwill Impairment, Change in Accounts Receivable, Change in
Inventory, Change in Accounts Payable, Net Cash Provided by Operating
Activities, Capital Expenditures, Purchases of Investments, Proceeds from
Sales/Maturities of Investments, Acquisitions, Net Cash Used in Investing
Activities, Dividends Paid, Share Repurchases, Proceeds from Issuance of
Common Stock, Debt Issued, Debt Repaid, Net Cash Provided by Financing
Activities, Effect of Exchange Rate Changes on Cash, Net Change in Cash, Cash
at End of Period.

Some line items are legitimately absent for a given company/year because the
filer simply never tagged that concept (e.g. Apple doesn't report a separate
Goodwill/Intangible Assets line, or stopped breaking out Interest Expense
after FY2023) — the `Data Quality Check` sheet marks these `Missing` rather
than guessing or computing a derived value.

## How data is selected

- **Period filtering**: annual mode keeps only `10-K`/`10-K/A` facts with fiscal
  period `FY`; quarterly mode keeps only `10-Q`/`10-Q/A` facts with fiscal period
  `Q1`–`Q4`.
- **Units**: dollar line items require unit `USD`, EPS line items require
  `USD/shares`, share-count line items require `shares`, and ratio line items
  (e.g. Effective Tax Rate) require `pure`.
- **De-duplication**: a single filing can tag facts for more than one *actual*
  reporting period under the same fiscal_year/fiscal_period label — e.g. a
  10-Q's Q2 numbers include the discrete quarter, the prior-year comparative
  quarter, and a cumulative year-to-date figure, all sharing the same label.
  The tool resolves this by (1) keeping only the most recent "end" date,
  (2) among ties, keeping the shortest span (discrete period over cumulative
  YTD), (3) preferring a non-amended filing over an amended (`/A`) one, and
  (4) among any remaining ties, picking the most recently filed value.
- **Fallback tags**: each standard line item has a primary XBRL tag plus one or
  more fallback tags (e.g. Revenue tries `Revenues`, then
  `RevenueFromContractWithCustomerExcludingAssessedTax`, then `SalesRevenueNet`,
  ...). The `Data Quality Check` sheet records whenever a fallback tag was used.
- **Missing data**: if no candidate tag has a value for a given line item/period,
  the cell is left blank (`None`) and flagged as `Missing` in the quality sheet —
  this is expected for younger/smaller filers or discontinued line items, not an
  error.

## Caching & rate limiting

All GET requests go through `SECClient`, which:

- adds the required `User-Agent` header,
- enforces a minimum interval between requests (`EDGAR_RATE_LIMIT`, default 8/s),
- caches every successful JSON response on disk under `EDGAR_CACHE_DIR`
  (`data/cache` by default), keyed by URL hash, so re-running the same company
  doesn't re-hit SEC,
- retries with exponential backoff on `429` and `5xx` responses (honoring
  `Retry-After` when present), and
- raises clear exceptions for `403` (bad/missing User-Agent), `404` (unknown
  CIK/no data), and exhausted `429` retries.

Pass `--no-cache` to force fresh requests for a run.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

Tests cover CIK normalization, ticker-to-CIK lookup, annual/quarterly fact
filtering and de-duplication, fallback-tag selection when building statements,
and end-to-end Excel workbook generation — all without hitting the network
(SEC responses are stubbed).

## Notes

- The Company Facts API only returns consolidated (non-segment) values, so no
  dimensional/member filtering is required to get top-level statement figures.
- Some smaller or newly-public filers may not report every standard tag (or its
  fallbacks) for every year — check the `Data Quality Check` sheet to see exactly
  what was found, what was a fallback, and what was missing.
