"""Filtering, unit selection, and de-duplication of raw XBRL facts.

Rules implemented (per project spec):
 - annual mode keeps only 10-K / 10-K/A facts with fiscal_period == "FY"
 - quarterly mode keeps only 10-Q / 10-Q/A facts with fiscal_period in Q1..Q4
 - EPS values are restricted to unit "USD/shares", share counts to "shares",
   everything else defaults to "USD"
 - de-duplication: for the same (tag, fiscal_year, fiscal_period, unit),
   prefer a non-amended filing; among remaining candidates prefer the most
   recently filed one. Amended filings are only used if no normal filing exists.
"""

from __future__ import annotations

import pandas as pd

ANNUAL_FORMS = {"10-K", "10-K/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
VALID_FISCAL_PERIODS_QUARTERLY = {"Q1", "Q2", "Q3", "Q4"}


class FactFilterError(Exception):
    """Raised for invalid filter parameters."""


def filter_by_period(df: pd.DataFrame, period_type: str) -> pd.DataFrame:
    if period_type not in ("annual", "quarterly"):
        raise FactFilterError(f"period_type must be 'annual' or 'quarterly', got '{period_type}'")

    df = df.dropna(subset=["fiscal_year", "fiscal_period"])

    if period_type == "annual":
        mask = df["form"].isin(ANNUAL_FORMS) & (df["fiscal_period"] == "FY")
    else:
        mask = df["form"].isin(QUARTERLY_FORMS) & df["fiscal_period"].isin(
            VALID_FISCAL_PERIODS_QUARTERLY
        )

    return df.loc[mask].copy()


def filter_by_year_range(df: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    mask = (df["fiscal_year"] >= start_year) & (df["fiscal_year"] <= end_year)
    return df.loc[mask].copy()


def filter_by_unit(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    if unit == "USD":
        mask = df["unit"] == "USD"
    elif unit == "USD/shares":
        mask = df["unit"] == "USD/shares"
    elif unit == "shares":
        mask = df["unit"] == "shares"
    else:
        mask = df["unit"] == unit
    return df.loc[mask].copy()


def _is_amended(form) -> bool:
    return isinstance(form, str) and form.endswith("/A")


def dedupe_facts(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse multiple reported values for the same (tag, fy, fp, unit) to one row.

    A single filing tags facts for more than one *actual* reporting period under
    the same fiscal_year/fiscal_period label: the current period, its prior-year
    comparative, and -- for duration facts -- a cumulative year-to-date span
    alongside the discrete period (e.g. a 10-Q's Q2 revenue includes both the
    discrete quarter and the 6-month year-to-date figure). Resolution order:
      1. keep only the most recent "end" date (drops prior-year comparatives)
      2. among ties, keep the shortest span (drops cumulative YTD in favor of
         the discrete period; instant facts have no start/duration and are
         unaffected)
      3. prefer a non-amended filing
      4. among remaining ties, the most recently filed row wins
    """
    if df.empty:
        return df

    group_cols = ["tag", "fiscal_year", "fiscal_period", "unit"]
    df = df.copy()

    max_end = df.groupby(group_cols)["end"].transform("max")
    df = df[df["end"] == max_end].copy()

    duration = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).where(df["start"].notna())
    df["_duration"] = duration
    min_duration = df.groupby(group_cols)["_duration"].transform("min")
    df = df[df["_duration"].isna() | (df["_duration"] == min_duration)].copy()
    df = df.drop(columns=["_duration"])

    df["_is_amended"] = df["form"].apply(_is_amended)
    # Sort so that, within each remaining group, non-amended rows come first
    # and, among ties, the most recently filed row comes first.
    # drop_duplicates(keep="first") then selects exactly the row the spec asks for.
    df = df.sort_values(["_is_amended", "filed"], ascending=[True, False])
    deduped = df.drop_duplicates(subset=group_cols, keep="first")
    return deduped.drop(columns=["_is_amended"]).reset_index(drop=True)


def prepare_facts(
    df: pd.DataFrame, period_type: str, start_year: int, end_year: int
) -> pd.DataFrame:
    """Full pipeline: period filter -> year range filter -> de-dupe."""
    df = filter_by_period(df, period_type)
    df = filter_by_year_range(df, start_year, end_year)
    df = dedupe_facts(df)
    return df
