"""Series registry and shared paths for the macro dashboard.

To track a new series, add one entry to SERIES below with its label and
source ("fred" or "alpha_vantage") -- nothing else in the codebase needs
to change.
"""

from pathlib import Path

SERIES = {
    "GDP": {"label": "Gross Domestic Product", "source": "fred"},
    "CPIAUCSL": {"label": "Consumer Price Index (CPI-U)", "source": "fred"},
    "UNRATE": {"label": "Unemployment Rate", "source": "fred"},
    "FEDFUNDS": {"label": "Effective Federal Funds Rate", "source": "fred"},
    "DGS10": {"label": "10-Year Treasury Yield", "source": "fred"},
    "M2SL": {"label": "M2 Money Supply", "source": "fred"},
    "WTI": {"label": "Crude Oil (WTI)", "source": "alpha_vantage"},
    "NATURAL_GAS": {"label": "Henry Hub Natural Gas", "source": "alpha_vantage"},
    "COPPER": {"label": "Copper", "source": "alpha_vantage"},
}

DATA_DIR = Path(__file__).parent / "data"

FRED_API_KEY_ENV_VAR = "FRED_API_KEY"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

ALPHA_VANTAGE_API_KEY_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
