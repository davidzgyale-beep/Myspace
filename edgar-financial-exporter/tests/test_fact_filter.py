import pandas as pd

from edgar_exporter.fact_filter import (
    dedupe_facts,
    filter_by_period,
    filter_by_unit,
    filter_by_year_range,
    prepare_facts,
)


def _row(**kwargs):
    base = {
        "taxonomy": "us-gaap",
        "tag": "Revenues",
        "label": "Revenues",
        "description": "desc",
        "unit": "USD",
        "value": 100,
        "fiscal_year": 2022,
        "fiscal_period": "FY",
        "form": "10-K",
        "filed": "2023-01-01",
        "frame": None,
        "accession_number": "0000000000-23-000001",
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    base.update(kwargs)
    return base


def test_filter_by_period_annual_keeps_only_10k_fy():
    df = pd.DataFrame([_row(form="10-K", fiscal_period="FY"), _row(form="10-Q", fiscal_period="Q1")])
    out = filter_by_period(df, "annual")
    assert len(out) == 1
    assert out.iloc[0]["form"] == "10-K"


def test_filter_by_period_quarterly_keeps_only_10q():
    df = pd.DataFrame([_row(form="10-K", fiscal_period="FY"), _row(form="10-Q", fiscal_period="Q1")])
    out = filter_by_period(df, "quarterly")
    assert len(out) == 1
    assert out.iloc[0]["form"] == "10-Q"


def test_filter_by_year_range():
    df = pd.DataFrame([_row(fiscal_year=y) for y in [2019, 2020, 2021, 2022]])
    out = filter_by_year_range(df, 2020, 2021)
    assert sorted(out["fiscal_year"].tolist()) == [2020, 2021]


def test_filter_by_unit_eps_only_keeps_usd_per_share():
    df = pd.DataFrame([_row(unit="USD"), _row(unit="USD/shares")])
    out = filter_by_unit(df, "USD/shares")
    assert len(out) == 1
    assert out.iloc[0]["unit"] == "USD/shares"


def test_dedupe_prefers_latest_filed_non_amended():
    df = pd.DataFrame(
        [
            _row(value=100, filed="2023-01-01", form="10-K", accession_number="A"),
            _row(value=105, filed="2023-06-01", form="10-K", accession_number="B"),
            _row(value=999, filed="2023-12-01", form="10-K/A", accession_number="C"),
        ]
    )
    out = dedupe_facts(df)
    assert len(out) == 1
    assert out.iloc[0]["value"] == 105
    assert out.iloc[0]["accession_number"] == "B"


def test_dedupe_falls_back_to_amended_if_only_option():
    df = pd.DataFrame([_row(value=999, filed="2023-12-01", form="10-K/A", accession_number="C")])
    out = dedupe_facts(df)
    assert len(out) == 1
    assert out.iloc[0]["value"] == 999


def test_dedupe_picks_discrete_quarter_over_comparative_and_ytd():
    # Real-world SEC quirk: a single 10-Q tags facts covering several actual
    # periods (prior-year comparative quarter, prior-year YTD, current
    # discrete quarter, current YTD) all under the SAME fiscal_year/fiscal_period
    # and the SAME filed date. dedupe_facts must pick the current discrete
    # quarter, not the comparative year or the cumulative year-to-date figure.
    df = pd.DataFrame(
        [
            _row(value=97045000000, start="2021-07-01", end="2021-12-31", accession_number="A"),  # prior-year YTD
            _row(value=51728000000, start="2021-10-01", end="2021-12-31", accession_number="B"),  # prior-year discrete
            _row(value=102869000000, start="2022-07-01", end="2022-12-31", accession_number="C"),  # current YTD
            _row(value=52747000000, start="2022-10-01", end="2022-12-31", accession_number="D"),  # current discrete
        ]
    )
    df["fiscal_year"] = 2023
    df["fiscal_period"] = "Q2"

    out = dedupe_facts(df)

    assert len(out) == 1
    assert out.iloc[0]["value"] == 52747000000
    assert out.iloc[0]["accession_number"] == "D"


def test_prepare_facts_pipeline_filters_and_dedupes():
    df = pd.DataFrame(
        [
            _row(fiscal_year=2020, filed="2021-01-01", accession_number="A"),
            _row(fiscal_year=2020, filed="2021-02-01", accession_number="B"),
            _row(fiscal_year=2025, filed="2026-01-01", accession_number="C"),
        ]
    )
    out = prepare_facts(df, "annual", 2019, 2021)
    assert len(out) == 1
    assert out.iloc[0]["accession_number"] == "B"
