"""Data-quality reporting: per-cell tag provenance, cross-statement reconciliation
checks, and period-over-period anomaly detection for the workbook's
Data Quality Check sheet.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

import pandas as pd

COMBINED_COLUMNS = [
    "Statement",
    "Statement Line Item",
    "Period",
    "Status",
    "Source Tag",
    "Fallback Tag Used",
    "Unit",
    "Filed Date",
    "Accession Number",
]

RECONCILIATION_COLUMNS = ["Check", "Period", "Value A", "Value B", "Difference", "Status", "Note"]

ANOMALY_COLUMNS = [
    "Statement",
    "Line Item",
    "Period",
    "Compared To",
    "Value",
    "Prior Value",
    "Change %",
    "Flag",
]

_PERIOD_RE = re.compile(r"^(?:FY(\d{4})|(\d{4})(Q[1-4]))$")
_QUARTER_ORDER = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


def combine_quality_reports(quality_by_statement: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Stack each statement's quality DataFrame, tagging rows with their statement name."""
    frames = []
    for statement_name, qdf in quality_by_statement.items():
        if qdf.empty:
            continue
        qdf = qdf.copy()
        qdf.insert(0, "Statement", statement_name)
        frames.append(qdf)

    if not frames:
        return pd.DataFrame(columns=COMBINED_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    return combined[COMBINED_COLUMNS]


def summarize_quality(combined: pd.DataFrame) -> pd.DataFrame:
    """Roll up the combined quality report into a small summary table."""
    if combined.empty:
        return pd.DataFrame(columns=["Metric", "Value"])

    total = len(combined)
    ok = int((combined["Status"] == "OK").sum())
    fallback = int((combined["Status"] == "Fallback Used").sum())
    missing = int((combined["Status"] == "Missing").sum())
    missing_pct = f"{missing / total * 100:.1f}%" if total else "0.0%"

    return pd.DataFrame(
        [
            ("Total Line Item x Period Cells", total),
            ("OK (Primary Tag)", ok),
            ("Fallback Tag Used", fallback),
            ("Missing", missing),
            ("Missing %", missing_pct),
        ],
        columns=["Metric", "Value"],
    )


def _parse_period_label(label: str) -> Optional[Tuple[int, str]]:
    match = _PERIOD_RE.match(str(label))
    if not match:
        return None
    if match.group(1):
        return int(match.group(1)), "FY"
    return int(match.group(2)), match.group(3)


def _period_sort_key(label: str) -> Tuple[int, int]:
    parsed = _parse_period_label(label)
    if parsed is None:
        return (10**9, 10**9)
    year, period = parsed
    return (year, _QUARTER_ORDER.get(period, 9))


def _immediately_follows(prev_label: str, curr_label: str) -> bool:
    """True if curr_label is exactly one period after prev_label (no gaps)."""
    prev = _parse_period_label(prev_label)
    curr = _parse_period_label(curr_label)
    if prev is None or curr is None:
        return False
    prev_year, prev_period = prev
    curr_year, curr_period = curr
    if prev_period == "FY" and curr_period == "FY":
        return curr_year == prev_year + 1
    if prev_period.startswith("Q") and curr_period.startswith("Q"):
        prev_idx = _QUARTER_ORDER[prev_period]
        if prev_idx == 4:
            return curr_year == prev_year + 1 and curr_period == "Q1"
        return curr_year == prev_year and _QUARTER_ORDER[curr_period] == prev_idx + 1
    return False


def _get_row_values(df: pd.DataFrame, line_item: str) -> Dict[str, float]:
    """Return {period_label: value} for a line item, or {} if the statement/row is absent."""
    if df is None or df.empty or "Line Item" not in df.columns:
        return {}
    match = df[df["Line Item"] == line_item]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {col: row[col] for col in df.columns if col != "Line Item"}


def _diff(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    return a - b


def build_reconciliation_checks(
    statements: Dict[str, pd.DataFrame], tolerance: float = 1.0
) -> pd.DataFrame:
    """Cross-check statement totals that should always tie out exactly (within `tolerance`
    dollars) if the underlying facts were pulled and mapped correctly:
      - Total Assets == Total Liabilities and Equity (Balance Sheet)
      - Net Income agrees between the Income Statement and Cash Flow Statement
      - Cash at End of Period (Cash Flow Statement) agrees with Cash and Cash
        Equivalents (Balance Sheet)
      - Net Change in Cash agrees with the period-over-period change in Cash at
        End of Period

    A "Mismatch" here is a strong signal of a tag-mapping or de-duplication bug
    (this is exactly the kind of error that a wrong fallback tag or a wrong
    duration/period selection would produce).
    """
    income = statements.get("Income Statement", pd.DataFrame())
    balance = statements.get("Balance Sheet", pd.DataFrame())
    cashflow = statements.get("Cash Flow Statement", pd.DataFrame())

    rows = []

    def _add(check_name: str, values_a: Dict[str, float], values_b: Dict[str, float], note: str = ""):
        periods = sorted(set(values_a) | set(values_b), key=_period_sort_key)
        for period in periods:
            a = values_a.get(period)
            b = values_b.get(period)
            diff = _diff(a, b)
            if diff is None:
                status = "N/A"
            elif abs(diff) <= tolerance:
                status = "OK"
            else:
                status = "Mismatch"
            rows.append(
                {
                    "Check": check_name,
                    "Period": period,
                    "Value A": a,
                    "Value B": b,
                    "Difference": diff,
                    "Status": status,
                    "Note": note,
                }
            )

    _add(
        "Total Assets = Total Liabilities and Equity",
        _get_row_values(balance, "Total Assets"),
        _get_row_values(balance, "Total Liabilities and Equity"),
    )
    _add(
        "Net Income: Income Statement vs. Cash Flow Statement",
        _get_row_values(income, "Net Income"),
        _get_row_values(cashflow, "Net Income"),
    )
    _add(
        "Cash at End of Period: Cash Flow Statement vs. Balance Sheet",
        _get_row_values(cashflow, "Cash at End of Period"),
        _get_row_values(balance, "Cash and Cash Equivalents"),
        note=(
            "A mismatch can be legitimate if the Cash Flow Statement's cash figure "
            "includes restricted cash that the Balance Sheet reports separately."
        ),
    )

    cash_end = _get_row_values(cashflow, "Cash at End of Period")
    net_change = _get_row_values(cashflow, "Net Change in Cash")
    ordered_periods = sorted(cash_end.keys(), key=_period_sort_key)
    computed_change: Dict[str, float] = {}
    reported_change: Dict[str, float] = {}
    for prev_period, curr_period in zip(ordered_periods, ordered_periods[1:]):
        if not _immediately_follows(prev_period, curr_period):
            continue
        prev_val, curr_val = cash_end.get(prev_period), cash_end.get(curr_period)
        if prev_val is None or curr_val is None or pd.isna(prev_val) or pd.isna(curr_val):
            continue
        computed_change[curr_period] = curr_val - prev_val
        reported_change[curr_period] = net_change.get(curr_period)
    _add(
        "Net Change in Cash vs. change in Cash at End of Period",
        computed_change,
        reported_change,
        note="Value A is this period's Cash at End of Period minus the prior period's.",
    )

    return pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)


def detect_anomalies(
    statements: Dict[str, pd.DataFrame], threshold: float = 0.5
) -> pd.DataFrame:
    """Flag line items whose period-over-period change looks suspicious: a swing of at
    least `threshold` (50% by default) or a sign flip between positive and negative.

    For annual periods the comparison is against the immediately preceding column.
    For quarterly periods the comparison is against the *same quarter one year
    earlier* (to avoid flagging ordinary seasonality as an anomaly); if that
    comparable quarter isn't present, the line item/period is skipped.

    This does not mean the flagged value is wrong -- some swings are real
    (e.g. a one-off tax charge) -- but it is worth a human glance, and it is
    exactly the kind of check that would have caught the "quarterly duration
    figure was actually a cumulative year-to-date value" bug during development.
    """
    rows = []

    for statement_name, df in statements.items():
        if df.empty or "Line Item" not in df.columns:
            continue
        period_cols = [c for c in df.columns if c != "Line Item"]
        sorted_cols = sorted(period_cols, key=_period_sort_key)

        for _, row in df.iterrows():
            line_item = row["Line Item"]
            for i, curr_label in enumerate(sorted_cols):
                comparable_label = _find_comparable_period(sorted_cols, i)
                if comparable_label is None:
                    continue
                value = row[curr_label]
                prior_value = row[comparable_label]
                if value is None or prior_value is None or pd.isna(value) or pd.isna(prior_value):
                    continue
                if prior_value == 0:
                    continue

                change_pct = (value - prior_value) / abs(prior_value)
                flags = []
                if abs(change_pct) >= threshold:
                    flags.append(f"|change| >= {threshold:.0%}")
                if (value > 0) != (prior_value > 0):
                    flags.append("sign flip")
                if not flags:
                    continue

                rows.append(
                    {
                        "Statement": statement_name,
                        "Line Item": line_item,
                        "Period": curr_label,
                        "Compared To": comparable_label,
                        "Value": value,
                        "Prior Value": prior_value,
                        "Change %": change_pct,
                        "Flag": "; ".join(flags),
                    }
                )

    return pd.DataFrame(rows, columns=ANOMALY_COLUMNS)


def _find_comparable_period(sorted_cols, index: int) -> Optional[str]:
    curr = sorted_cols[index]
    parsed = _parse_period_label(curr)
    if parsed is None:
        return None
    year, period = parsed
    if period == "FY":
        return sorted_cols[index - 1] if index > 0 else None
    target = f"{year - 1}{period}"
    return target if target in sorted_cols else None
