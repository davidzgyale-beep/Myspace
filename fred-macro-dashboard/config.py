"""Series registry and shared paths for the macro dashboard.

To track a new series, add one entry to SERIES below with its label,
source ("fred" or "alpha_vantage"), and native unit -- nothing else in
the codebase needs to change.
"""

from pathlib import Path

SERIES = {
    "GDP": {"label": "Gross Domestic Product", "source": "fred", "unit": "Billions of USD"},
    "CPIAUCSL": {"label": "Consumer Price Index (CPI-U)", "source": "fred", "unit": "Index (1982-84=100)"},
    "UNRATE": {"label": "Unemployment Rate", "source": "fred", "unit": "Percent"},
    "FEDFUNDS": {"label": "Effective Federal Funds Rate", "source": "fred", "unit": "Percent"},
    "DGS10": {"label": "10-Year Treasury Yield", "source": "fred", "unit": "Percent"},
    "M2SL": {"label": "M2 Money Supply", "source": "fred", "unit": "Billions of USD"},
    "WTI": {"label": "Crude Oil (WTI)", "source": "alpha_vantage", "unit": "USD per barrel"},
    "NATURAL_GAS": {"label": "Henry Hub Natural Gas", "source": "alpha_vantage", "unit": "USD per MMBtu"},
    "COPPER": {"label": "Copper", "source": "alpha_vantage", "unit": "USD per metric ton"},
}

DATA_DIR = Path(__file__).parent / "data"

FRED_API_KEY_ENV_VAR = "FRED_API_KEY"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

ALPHA_VANTAGE_API_KEY_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
