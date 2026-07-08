import numpy as np
import pandas as pd
import pytest

import transform


def _df(dates, values):
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def test_pct_change_basic():
    df = _df(["2024-01-01", "2024-02-01", "2024-03-01"], [100, 110, 121])

    result = transform.pct_change(df)

    assert pd.isna(result["value"].iloc[0])
    assert result["value"].iloc[1] == pytest.approx(10.0)
    assert result["value"].iloc[2] == pytest.approx(10.0)


def test_yoy_pct_change_matches_prior_year_and_handles_gap():
    dates = pd.date_range("2023-01-01", periods=18, freq="MS")
    values = [100 + 10 * i for i in range(18)]
    values[5] = np.nan  # gap at 2023-06-01, which is the YoY anchor for 2024-06-01
    df = pd.DataFrame({"date": dates, "value": values})

    result = transform.yoy_pct_change(df)
    result = result.set_index("date")

    # 2024-01-01 (220) vs 2023-01-01 (100) -> +120%
    assert result.loc["2024-01-01", "value"] == pytest.approx(120.0)

    # 2024-06-01's anchor (2023-06-01) is missing, so YoY should be NaN, not silently wrong
    assert pd.isna(result.loc["2024-06-01", "value"])


def test_yoy_pct_change_quarterly_frequency():
    dates = pd.date_range("2022-01-01", periods=8, freq="QS")
    values = [200 + 5 * i for i in range(8)]
    df = pd.DataFrame({"date": dates, "value": values})

    result = transform.yoy_pct_change(df).set_index("date")

    # 2023-01-01 (220) vs 2022-01-01 (200) -> +10%
    assert result.loc["2023-01-01", "value"] == pytest.approx(10.0)
    # First year has no prior-year anchor
    assert pd.isna(result.loc["2022-01-01", "value"])


def test_latest_summary_basic():
    df = _df(["2024-01-01", "2024-02-01", "2024-03-01"], [100, 110, 121])

    summary = transform.latest_summary(df)

    assert summary["latest_value"] == 121
    assert summary["prior_value"] == 110
    assert summary["change"] == pytest.approx(11.0)
    assert summary["pct_change"] == pytest.approx(10.0)


def test_latest_summary_skips_trailing_nan():
    df = _df(["2024-01-01", "2024-02-01", "2024-03-01"], [100, 110, np.nan])

    summary = transform.latest_summary(df)

    assert summary["latest_value"] == 110
    assert summary["prior_value"] == 100


def test_latest_summary_empty_df():
    df = _df([], [])

    summary = transform.latest_summary(df)

    assert summary["latest_value"] is None
    assert summary["change"] is None


def test_apply_transform_dispatch():
    df = _df(["2024-01-01", "2024-02-01"], [100, 110])

    assert transform.apply_transform(df, transform.LEVEL)["value"].tolist() == [100, 110]
    assert transform.apply_transform(df, transform.PCT_CHANGE)["value"].iloc[1] == pytest.approx(10.0)

    with pytest.raises(ValueError):
        transform.apply_transform(df, "not_a_real_mode")
