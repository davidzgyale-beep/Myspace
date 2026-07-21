#!/usr/bin/env python3
"""Backtest the dashboard's historical A/B/C labels without look-ahead data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
DATA_DIR = APP_DIR / "data"
OVERHEAT_THRESHOLD = 90
LOOKBACK_YEARS = 3
BACKTEST_HORIZONS = (5, 20, 120)


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True, na_option="keep")


def trailing_return(prices: pd.DataFrame, position: int, sessions: int) -> pd.Series:
    return prices.iloc[position] / prices.iloc[position - sessions] - 1


def classify_group(frame: pd.DataFrame) -> pd.Series:
    enough_data = frame["trading_days"] >= 121
    confirmed = (
        (frame["ret_20d"] > 0)
        & (frame["ret_60d"] > 0)
        & frame["above_ma20"]
        & frame["above_ma60"]
    )
    group_a = (
        enough_data
        & (frame["momentum_score"] >= 70)
        & confirmed
        & (frame["overheat_score"] < OVERHEAT_THRESHOLD)
    )
    group_b = enough_data & (frame["momentum_score"] >= 40) & (frame["ret_20d"] > -0.05)
    return pd.Series(np.select([group_a, group_b], ["A", "B"], default="C"), index=frame.index)


def snapshot_metrics(
    prices: pd.DataFrame,
    raw_prices: pd.DataFrame,
    position: int,
    subindustry: pd.Series,
) -> pd.DataFrame:
    close = prices.iloc[position]
    metrics = pd.DataFrame(index=prices.columns)
    metrics["trading_days"] = raw_prices.iloc[: position + 1].notna().sum()
    weights = {"ret_5d": 0.10, "ret_20d": 0.30, "ret_60d": 0.35, "ret_120d": 0.15}
    for column, weight in weights.items():
        sessions = int(column.split("_")[1][:-1])
        metrics[column] = trailing_return(prices, position, sessions)
        metrics[f"{column}_market_pct"] = percentile(metrics[column])
        metrics[f"{column}_sub_pct"] = metrics[column].groupby(subindustry).rank(pct=True)

    ma20 = prices.iloc[position - 19 : position + 1].mean()
    ma60 = prices.iloc[position - 59 : position + 1].mean()
    high60 = prices.iloc[position - 59 : position + 1].max()
    metrics["ma20_gap"] = close / ma20 - 1
    metrics["ma60_gap"] = close / ma60 - 1
    metrics["drawdown_60d"] = close / high60 - 1
    metrics["above_ma20"] = close > ma20
    metrics["above_ma60"] = close > ma60

    market_component = sum(metrics[f"{column}_market_pct"] * weight for column, weight in weights.items())
    subindustry_component = sum(metrics[f"{column}_sub_pct"] * weight for column, weight in weights.items())
    trend_component = (
        metrics["ma20_gap"].clip(-0.20, 0.20).add(0.20).div(0.40) * 0.05
        + metrics["drawdown_60d"].clip(-0.30, 0).add(0.30).div(0.30) * 0.05
    )
    metrics["momentum_score"] = (
        market_component * 0.65 + subindustry_component * 0.25 + trend_component
    ).mul(100).clip(0, 100).fillna(0)
    metrics["overheat_score"] = (
        percentile(metrics["ret_20d"]) * 0.30
        + percentile(metrics["ma20_gap"]) * 0.35
        + percentile(metrics["ma60_gap"]) * 0.20
        + percentile(metrics["drawdown_60d"]) * 0.15
    ).mul(100).clip(0, 100).fillna(0)
    metrics["group"] = classify_group(metrics)
    return metrics


def backtest_horizon(
    prices: pd.DataFrame,
    raw_prices: pd.DataFrame,
    subindustry: pd.Series,
    forward_sessions: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    last_entry_date = prices.index[-forward_sessions - 1]
    start_date = last_entry_date - pd.DateOffset(years=LOOKBACK_YEARS)
    first_position = max(120, int(prices.index.searchsorted(start_date)))
    # Anchor on the most recent eligible entry date, then step backwards in non-overlapping blocks.
    last_position = len(prices) - forward_sessions - 1
    positions = list(range(last_position, first_position - 1, -forward_sessions))[::-1]

    observations = []
    for position in positions:
        metrics = snapshot_metrics(prices, raw_prices, position, subindustry)
        entry_close = prices.iloc[position]
        exit_close = prices.iloc[position + forward_sessions]
        future_return = exit_close / entry_close - 1
        future_path = prices.iloc[position + 1 : position + forward_sessions + 1].div(entry_close, axis=1) - 1
        future_drawdown = future_path.min()
        frame = metrics[["group", "momentum_score", "overheat_score"]].copy()
        frame["entry_date"] = prices.index[position]
        frame["exit_date"] = prices.index[position + forward_sessions]
        frame["forward_return"] = future_return
        frame["forward_drawdown"] = future_drawdown
        frame.index.name = "ts_code"
        observations.append(frame.reset_index())

    detail = pd.concat(observations, ignore_index=True).dropna(
        subset=["forward_return", "forward_drawdown"]
    )
    period_returns = (
        detail.groupby(["entry_date", "exit_date", "group"], as_index=False)
        .agg(
            average_forward_return=("forward_return", "mean"),
            average_forward_drawdown=("forward_drawdown", "mean"),
            observation_count=("ts_code", "count"),
        )
    )
    summary = (
        period_returns.groupby("group", as_index=False)
        .agg(
            average_forward_return=("average_forward_return", "mean"),
            median_period_return=("average_forward_return", "median"),
            win_rate=("average_forward_return", lambda values: float((values > 0).mean())),
            average_forward_drawdown=("average_forward_drawdown", "mean"),
            rebalance_count=("entry_date", "nunique"),
        )
        .sort_values("group")
    )
    summary = summary.merge(
        detail.groupby("group")["ts_code"].count().rename("observation_count"),
        on="group",
        how="left",
    )
    yearly = (
        period_returns.assign(year=period_returns["entry_date"].dt.year)
        .groupby(["year", "group"], as_index=False)
        .agg(
            average_forward_return=("average_forward_return", "mean"),
            win_rate=("average_forward_return", lambda values: float((values > 0).mean())),
            rebalance_count=("entry_date", "nunique"),
        )
    )
    summary = summary.merge(
        yearly.groupby("group")["average_forward_return"].std().rename("annual_average_dispersion"),
        on="group",
        how="left",
    )
    summary.insert(0, "horizon_sessions", forward_sessions)
    yearly.insert(1, "horizon_sessions", forward_sessions)
    metadata = {
        "start_entry_date": detail["entry_date"].min().strftime("%Y-%m-%d"),
        "end_entry_date": detail["entry_date"].max().strftime("%Y-%m-%d"),
        "last_exit_date": detail["exit_date"].max().strftime("%Y-%m-%d"),
        "forward_sessions": forward_sessions,
        "rebalance_sessions": forward_sessions,
        "rebalance_count": int(detail["entry_date"].nunique()),
        "observation_count": int(len(detail)),
    }
    return summary, yearly, metadata


def build_backtest(source_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    universe = pd.read_csv(
        source_dir / "a_share_healthcare_universe.csv",
        usecols=["ts_code", "healthcare_subindustry"],
    )
    prices = pd.read_csv(
        source_dir / "a_share_healthcare_prices_qfq_wide.csv",
        index_col=0,
        parse_dates=True,
    ).sort_index()
    prices = prices.reindex(columns=universe["ts_code"])
    raw_prices = prices.copy()
    prices = prices.ffill(limit=3)
    subindustry = universe.set_index("ts_code")["healthcare_subindustry"]

    results = [
        backtest_horizon(prices, raw_prices, subindustry, horizon)
        for horizon in BACKTEST_HORIZONS
    ]
    summary = pd.concat([result[0] for result in results], ignore_index=True)
    yearly = pd.concat([result[1] for result in results], ignore_index=True)
    metadata = {
        "lookback_years": LOOKBACK_YEARS,
        "horizons": {str(horizon): result[2] for horizon, result in zip(BACKTEST_HORIZONS, results)},
        "universe_note": "使用当前310只股票的历史数据，存在幸存者偏差。",
    }
    return summary, yearly, metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    summary_frame, yearly_frame, meta = build_backtest(args.source_dir.resolve())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary_frame.to_csv(DATA_DIR / "group_backtest_summary.csv", index=False, encoding="utf-8-sig")
    yearly_frame.to_csv(DATA_DIR / "group_backtest_yearly.csv", index=False, encoding="utf-8-sig")
    (DATA_DIR / "group_backtest_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary_frame.to_string(index=False))
