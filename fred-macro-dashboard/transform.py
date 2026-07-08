"""Pandas transforms for FRED series: level, % change, YoY % change, and summary stats.

Every function takes/returns a DataFrame with ``date`` and ``value`` columns,
the same shape produced by fetch.get_series.
"""

import pandas as pd

LEVEL = "level"
PCT_CHANGE = "pct_change"
YOY = "yoy"


def pct_change(df: pd.DataFrame) -> pd.DataFrame:
    """Period-over-period % change at the series' native frequency."""
    out = df.sort_values("date").reset_index(drop=True).copy()
    out["value"] = out["value"].pct_change() * 100
    return out


def yoy_pct_change(df: pd.DataFrame, tolerance_days: int = 20) -> pd.DataFrame:
    """Year-over-year % change, matched by calendar date rather than row count.

    Works across mixed frequencies (daily/monthly/quarterly) without any
    per-series configuration: each observation is matched against the most
    recent observation from ~1 year earlier, within `tolerance_days`.
    """
    base = df.sort_values("date").reset_index(drop=True).copy()

    prior = base.copy()
    prior["date"] = prior["date"] + pd.DateOffset(years=1)
    prior = prior.rename(columns={"value": "value_prior_year"})

    merged = pd.merge_asof(
        base,
        prior,
        on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=tolerance_days),
    )
    merged["value"] = (
        (merged["value"] - merged["value_prior_year"]) / merged["value_prior_year"] * 100
    )
    return merged[["date", "value"]]


def apply_transform(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == LEVEL:
        return df.sort_values("date").reset_index(drop=True)
    if mode == PCT_CHANGE:
        return pct_change(df)
    if mode == YOY:
        return yoy_pct_change(df)
    raise ValueError(f"Unknown transform mode: {mode!r}")


def latest_summary(df: pd.DataFrame) -> dict:
    """Latest value, prior value, and the change between them, from the two
    most recent non-null observations."""
    clean = df.dropna(subset=["value"]).sort_values("date")
    if len(clean) == 0:
        return {
            "latest_date": None,
            "latest_value": None,
            "prior_date": None,
            "prior_value": None,
            "change": None,
            "pct_change": None,
        }

    latest = clean.iloc[-1]
    if len(clean) < 2:
        return {
            "latest_date": latest["date"],
            "latest_value": latest["value"],
            "prior_date": None,
            "prior_value": None,
            "change": None,
            "pct_change": None,
        }

    prior = clean.iloc[-2]
    change = latest["value"] - prior["value"]
    pct = (change / prior["value"] * 100) if prior["value"] != 0 else None

    return {
        "latest_date": latest["date"],
        "latest_value": latest["value"],
        "prior_date": prior["date"],
        "prior_value": prior["value"],
        "change": change,
        "pct_change": pct,
    }
