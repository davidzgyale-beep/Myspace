"""Build wide financial statement tables (and their raw/long-format companions)
from a filtered, de-duplicated facts DataFrame using the standard line-item
mappings in statement_mappings.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from .fact_filter import filter_by_unit
from .statement_mappings import LineItemMapping

QUALITY_COLUMNS = [
    "Statement Line Item",
    "Period",
    "Status",
    "Source Tag",
    "Fallback Tag Used",
    "Unit",
    "Filed Date",
    "Accession Number",
]

RAW_FACTS_COLUMNS = [
    "taxonomy",
    "tag",
    "label",
    "description",
    "unit",
    "value",
    "fiscal_year",
    "fiscal_period",
    "form",
    "filed",
    "frame",
    "accession_number",
    "start",
    "end",
]

_QUARTER_ORDER = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


@dataclass(frozen=True)
class Period:
    fiscal_year: int
    fiscal_period: str  # "FY", "Q1".."Q4"

    @property
    def label(self) -> str:
        if self.fiscal_period == "FY":
            return f"FY{self.fiscal_year}"
        return f"{self.fiscal_year}{self.fiscal_period}"

    @property
    def sort_key(self) -> Tuple[int, int]:
        return (self.fiscal_year, _QUARTER_ORDER.get(self.fiscal_period, 9))


def _periods_from_df(df: pd.DataFrame) -> List[Period]:
    if df.empty:
        return []
    pairs = df[["fiscal_year", "fiscal_period"]].drop_duplicates()
    periods = {
        Period(int(row.fiscal_year), row.fiscal_period) for row in pairs.itertuples(index=False)
    }
    return sorted(periods, key=lambda p: p.sort_key)


def _select_fact(df: pd.DataFrame, tag: str, period: Period, unit: str) -> Optional[pd.Series]:
    subset = df[
        (df["tag"] == tag)
        & (df["fiscal_year"] == period.fiscal_year)
        & (df["fiscal_period"] == period.fiscal_period)
    ]
    subset = filter_by_unit(subset, unit)
    if subset.empty:
        return None
    # Facts are expected to already be de-duplicated to one row per
    # (tag, fiscal_year, fiscal_period, unit) by fact_filter.dedupe_facts.
    # Sorting by filed date is a defensive tie-break in case duplicates slip through.
    subset = subset.sort_values("filed", ascending=False)
    return subset.iloc[0]


def build_statement(
    df: pd.DataFrame, mapping: List[LineItemMapping]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Build one statement's wide table plus its per-cell data-quality rows.

    Returns:
        (wide_df, quality_df) where wide_df has columns ["Line Item", <period labels...>]
        and quality_df has one row per (line item, period) documenting which tag was
        used (including whether it was a fallback), unit, filing date, and accession
        number -- or that the value was missing entirely.
    """
    periods = _periods_from_df(df)
    period_labels = [p.label for p in periods]

    wide_rows = []
    quality_rows = []

    for item in mapping:
        row = {"Line Item": item.name}
        for period in periods:
            match = None
            used_tag = None
            for tag in item.tags:
                match = _select_fact(df, tag, period, item.unit)
                if match is not None:
                    used_tag = tag
                    break

            if match is not None:
                row[period.label] = match["value"]
                is_fallback = item.tags and used_tag != item.tags[0]
                quality_rows.append(
                    {
                        "Statement Line Item": item.name,
                        "Period": period.label,
                        "Status": "Fallback Used" if is_fallback else "OK",
                        "Source Tag": used_tag,
                        "Fallback Tag Used": used_tag if is_fallback else None,
                        "Unit": match["unit"],
                        "Filed Date": match["filed"],
                        "Accession Number": match["accession_number"],
                    }
                )
            else:
                row[period.label] = None
                quality_rows.append(
                    {
                        "Statement Line Item": item.name,
                        "Period": period.label,
                        "Status": "Missing",
                        "Source Tag": None,
                        "Fallback Tag Used": None,
                        "Unit": None,
                        "Filed Date": None,
                        "Accession Number": None,
                    }
                )
        wide_rows.append(row)

    wide_df = pd.DataFrame(wide_rows, columns=["Line Item"] + period_labels)
    quality_df = pd.DataFrame(quality_rows, columns=QUALITY_COLUMNS)
    return wide_df, quality_df


def build_raw_facts_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return the cleaned, filtered facts in a stable long format for the Raw Facts sheet."""
    if df.empty:
        return pd.DataFrame(columns=RAW_FACTS_COLUMNS)
    existing = [c for c in RAW_FACTS_COLUMNS if c in df.columns]
    out = df[existing].sort_values(["fiscal_year", "fiscal_period", "tag"]).reset_index(drop=True)
    return out
