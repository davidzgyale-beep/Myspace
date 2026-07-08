"""Series registry and shared paths for the FRED macro dashboard.

To track a new FRED series, add one entry to SERIES below -- nothing
else in the codebase needs to change.
"""

from pathlib import Path

SERIES = {
    "GDP": "Gross Domestic Product",
    "CPIAUCSL": "Consumer Price Index (CPI-U)",
    "UNRATE": "Unemployment Rate",
    "FEDFUNDS": "Effective Federal Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "M2SL": "M2 Money Supply",
}

DATA_DIR = Path(__file__).parent / "data"

FRED_API_KEY_ENV_VAR = "FRED_API_KEY"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
