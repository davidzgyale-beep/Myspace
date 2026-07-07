import pandas as pd

from edgar_exporter.statement_builder import build_raw_facts_table, build_statement
from edgar_exporter.statement_mappings import LineItemMapping


def _fact(**kwargs):
    base = {
        "taxonomy": "us-gaap",
        "tag": "Revenues",
        "label": "Revenues",
        "description": "desc",
        "unit": "USD",
        "value": 1000,
        "fiscal_year": 2022,
        "fiscal_period": "FY",
        "form": "10-K",
        "filed": "2023-01-01",
        "frame": None,
        "accession_number": "ACC-1",
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    base.update(kwargs)
    return base


def test_build_statement_uses_primary_tag_when_available():
    df = pd.DataFrame([_fact(tag="Revenues", value=1000)])
    mapping = [LineItemMapping("Revenue", ["Revenues", "SalesRevenueNet"])]

    wide_df, quality_df = build_statement(df, mapping)

    assert wide_df.loc[0, "FY2022"] == 1000
    assert quality_df.iloc[0]["Status"] == "OK"
    assert quality_df.iloc[0]["Source Tag"] == "Revenues"
    assert quality_df.iloc[0]["Fallback Tag Used"] is None


def test_build_statement_falls_back_to_secondary_tag():
    # Primary tag "Revenues" is absent; only the fallback "SalesRevenueNet" was reported.
    df = pd.DataFrame([_fact(tag="SalesRevenueNet", value=500)])
    mapping = [LineItemMapping("Revenue", ["Revenues", "SalesRevenueNet"])]

    wide_df, quality_df = build_statement(df, mapping)

    assert wide_df.loc[0, "FY2022"] == 500
    assert quality_df.iloc[0]["Status"] == "Fallback Used"
    assert quality_df.iloc[0]["Fallback Tag Used"] == "SalesRevenueNet"


def test_build_statement_marks_missing_when_no_tag_found():
    df = pd.DataFrame([_fact(tag="SomeUnmappedTag", value=1)])
    mapping = [LineItemMapping("Revenue", ["Revenues", "SalesRevenueNet"])]

    wide_df, quality_df = build_statement(df, mapping)

    assert pd.isna(wide_df.loc[0, "FY2022"])
    assert quality_df.iloc[0]["Status"] == "Missing"


def test_build_statement_respects_unit_constraint_for_eps():
    # A "USD" value should not satisfy an EPS line item requiring "USD/shares".
    df = pd.DataFrame([_fact(tag="EarningsPerShareBasic", value=42, unit="USD")])
    mapping = [LineItemMapping("EPS Basic", ["EarningsPerShareBasic"], unit="USD/shares")]

    wide_df, quality_df = build_statement(df, mapping)

    assert pd.isna(wide_df.loc[0, "FY2022"])
    assert quality_df.iloc[0]["Status"] == "Missing"


def test_build_raw_facts_table_sorted_and_has_expected_columns():
    df = pd.DataFrame([_fact(fiscal_year=2022), _fact(fiscal_year=2020)])
    raw = build_raw_facts_table(df)
    assert list(raw["fiscal_year"]) == [2020, 2022]
    assert "accession_number" in raw.columns
    assert "unit" in raw.columns
