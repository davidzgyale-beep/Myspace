import pandas as pd

from edgar_exporter.data_quality import build_reconciliation_checks, detect_anomalies


def test_reconciliation_flags_unbalanced_balance_sheet():
    statements = {
        "Balance Sheet": pd.DataFrame(
            {
                "Line Item": ["Total Assets", "Total Liabilities and Equity"],
                "FY2022": [1000, 1000],
                "FY2023": [1200, 1150],  # off by 50
            }
        ),
    }

    out = build_reconciliation_checks(statements)
    check = out[
        (out["Check"] == "Total Assets = Total Liabilities and Equity") & (out["Period"] == "FY2023")
    ].iloc[0]
    assert check["Status"] == "Mismatch"
    assert check["Difference"] == 50

    check_ok = out[
        (out["Check"] == "Total Assets = Total Liabilities and Equity") & (out["Period"] == "FY2022")
    ].iloc[0]
    assert check_ok["Status"] == "OK"


def test_reconciliation_net_income_cross_statement():
    statements = {
        "Income Statement": pd.DataFrame({"Line Item": ["Net Income"], "FY2022": [500]}),
        "Cash Flow Statement": pd.DataFrame({"Line Item": ["Net Income"], "FY2022": [493]}),
    }
    out = build_reconciliation_checks(statements)
    check = out[out["Check"] == "Net Income: Income Statement vs. Cash Flow Statement"].iloc[0]
    assert check["Status"] == "Mismatch"
    assert check["Difference"] == 7


def test_reconciliation_net_change_in_cash_skips_non_adjacent_quarters():
    # 2023Q3 -> 2024Q1 has a gap (no Q4), so the computed cash-diff check must skip it
    # rather than falsely flag a mismatch.
    statements = {
        "Cash Flow Statement": pd.DataFrame(
            {
                "Line Item": ["Net Income", "Net Change in Cash", "Cash at End of Period"],
                "2023Q1": [10, 5, 100],
                "2023Q2": [10, 20, 120],
                "2023Q3": [10, -10, 110],
                "2024Q1": [10, 999, 500],  # unrelated jump; should not be compared to 2023Q3
            }
        ),
    }
    out = build_reconciliation_checks(statements)
    change_checks = out[out["Check"] == "Net Change in Cash vs. change in Cash at End of Period"]
    periods_checked = set(change_checks["Period"])
    assert "2024Q1" not in periods_checked
    assert "2023Q2" in periods_checked
    assert "2023Q3" in periods_checked

    q2_row = change_checks[change_checks["Period"] == "2023Q2"].iloc[0]
    assert q2_row["Value A"] == 20  # 120 - 100
    assert q2_row["Status"] == "OK"


def test_detect_anomalies_flags_large_annual_swing():
    statements = {
        "Income Statement": pd.DataFrame(
            {"Line Item": ["Revenue"], "FY2021": [100], "FY2022": [1000]}
        ),
    }
    out = detect_anomalies(statements, threshold=0.5)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["Period"] == "FY2022"
    assert row["Compared To"] == "FY2021"
    assert "change" in row["Flag"]


def test_detect_anomalies_uses_same_quarter_yoy_not_qoq():
    # Q1 -> Q2 seasonal growth should NOT be flagged; Q1 2024 vs Q1 2023 should be.
    statements = {
        "Income Statement": pd.DataFrame(
            {
                "Line Item": ["Revenue"],
                "2023Q1": [50],
                "2023Q2": [200],  # large QoQ jump, but not compared QoQ
                "2024Q1": [150],  # 3x YoY vs 2023Q1 -> should be flagged
            }
        ),
    }
    out = detect_anomalies(statements, threshold=0.5)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["Period"] == "2024Q1"
    assert row["Compared To"] == "2023Q1"


def test_detect_anomalies_flags_sign_flip():
    statements = {
        "Income Statement": pd.DataFrame(
            {"Line Item": ["Total Other Income (Expense), Net"], "FY2021": [50], "FY2022": [-10]}
        ),
    }
    out = detect_anomalies(statements, threshold=10.0)  # high threshold so only sign flip triggers it
    assert len(out) == 1
    assert "sign flip" in out.iloc[0]["Flag"]


def test_detect_anomalies_ignores_missing_values():
    statements = {
        "Income Statement": pd.DataFrame(
            {"Line Item": ["Revenue"], "FY2021": [None], "FY2022": [1000]}
        ),
    }
    out = detect_anomalies(statements)
    assert out.empty
