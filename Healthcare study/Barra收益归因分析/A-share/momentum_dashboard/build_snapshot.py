#!/usr/bin/env python3
"""Build the deployment snapshot for the A-share healthcare momentum dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
DATA_DIR = APP_DIR / "data"
TARGET_COUNT = 310


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True, na_option="keep")


def trailing_return(prices: pd.DataFrame, sessions: int) -> pd.Series:
    if len(prices) <= sessions:
        return pd.Series(index=prices.columns, dtype=float)
    return prices.iloc[-1] / prices.iloc[-sessions - 1] - 1.0


def classify_temperature(row: pd.Series) -> str:
    if row["overheat_score"] >= 80:
        return "过热"
    if row["overheat_score"] >= 60:
        return "偏热"
    if row["overheat_score"] >= 35:
        return "中性"
    return "偏冷"


def classify_group(row: pd.Series) -> str:
    enough_data = row["trading_days"] >= 121
    trend_confirmed = row["ret_20d"] > 0 and row["ret_60d"] > 0 and row["above_ma20"] and row["above_ma60"]
    if enough_data and row["momentum_score"] >= 70 and trend_confirmed and row["overheat_score"] < 85:
        return "A"
    if enough_data and row["momentum_score"] >= 40 and row["ret_20d"] > -0.05:
        return "B"
    return "C"


def build_snapshot(source_dir: Path) -> None:
    universe_path = source_dir / "a_share_healthcare_universe.csv"
    prices_path = source_dir / "a_share_healthcare_prices_qfq_wide.csv"
    universe = pd.read_csv(universe_path, dtype={"symbol": "string"})
    prices = pd.read_csv(prices_path, index_col="trade_date", parse_dates=True)
    prices = prices.apply(pd.to_numeric, errors="coerce").sort_index()

    if len(universe) != TARGET_COUNT:
        raise ValueError(f"Expected {TARGET_COUNT} stocks, found {len(universe)}")
    missing = sorted(set(universe["ts_code"]) - set(prices.columns))
    if missing:
        raise ValueError(f"Price data missing {len(missing)} stocks: {missing[:5]}")

    prices = prices[universe["ts_code"].tolist()]
    latest_date = prices.index.max()
    raw_prices = prices.loc[:latest_date]
    latest = raw_prices.ffill(limit=3)
    close = latest.iloc[-1]
    metrics = pd.DataFrame(index=prices.columns)
    metrics.index.name = "ts_code"
    metrics["price_date"] = raw_prices.apply(lambda s: s.last_valid_index())
    metrics["latest_close_qfq"] = close
    metrics["trading_days"] = prices.notna().sum()

    for sessions in (5, 20, 60, 120, 250):
        metrics[f"ret_{sessions}d"] = trailing_return(latest, sessions)

    ma20 = latest.tail(20).mean()
    ma60 = latest.tail(60).mean()
    high60 = latest.tail(60).max()
    high250 = latest.tail(250).max()
    metrics["ma20_gap"] = close / ma20 - 1.0
    metrics["ma60_gap"] = close / ma60 - 1.0
    metrics["drawdown_60d"] = close / high60 - 1.0
    metrics["drawdown_250d"] = close / high250 - 1.0
    metrics["above_ma20"] = close > ma20
    metrics["above_ma60"] = close > ma60
    metrics = metrics.reset_index()

    keep = [
        "ts_code", "name", "healthcare_subindustry", "classification_confidence",
        "market", "total_mv_cny", "latest_turnover_rate", "latest_pe_ttm", "latest_pb",
    ]
    metrics = metrics.merge(universe[keep], on="ts_code", how="left", validate="one_to_one")
    metrics["market_cap_100m"] = pd.to_numeric(metrics["total_mv_cny"], errors="coerce") / 1e8

    return_cols = ["ret_5d", "ret_20d", "ret_60d", "ret_120d"]
    weights = {"ret_5d": 0.10, "ret_20d": 0.30, "ret_60d": 0.35, "ret_120d": 0.15}
    for col in return_cols:
        metrics[f"{col}_market_pct"] = percentile(metrics[col])
        metrics[f"{col}_sub_pct"] = metrics.groupby("healthcare_subindustry", dropna=False)[col].transform(percentile)

    market_component = sum(metrics[f"{col}_market_pct"] * weight for col, weight in weights.items())
    sub_component = sum(metrics[f"{col}_sub_pct"] * weight for col, weight in weights.items())
    trend_component = (
        metrics["ma20_gap"].clip(-0.20, 0.20).add(0.20).div(0.40) * 0.05
        + metrics["drawdown_60d"].clip(-0.30, 0).add(0.30).div(0.30) * 0.05
    )
    metrics["momentum_score"] = (market_component * 0.65 + sub_component * 0.25 + trend_component).mul(100).clip(0, 100)

    heat_raw = (
        percentile(metrics["ret_20d"]) * 0.30
        + percentile(metrics["ma20_gap"]) * 0.35
        + percentile(metrics["ma60_gap"]) * 0.20
        + percentile(metrics["drawdown_60d"]) * 0.15
    )
    metrics["overheat_score"] = heat_raw.mul(100).clip(0, 100)
    metrics[["momentum_score", "overheat_score"]] = metrics[["momentum_score", "overheat_score"]].fillna(0.0)
    metrics["temperature"] = metrics.apply(classify_temperature, axis=1)
    metrics["group"] = metrics.apply(classify_group, axis=1)
    metrics["subindustry_rank"] = metrics.groupby("healthcare_subindustry")["momentum_score"].rank(method="min", ascending=False).astype("Int64")
    metrics["subindustry_count"] = metrics.groupby("healthcare_subindustry")["ts_code"].transform("count")
    metrics["price_stale_days"] = (latest_date - pd.to_datetime(metrics["price_date"])).dt.days
    metrics = metrics.sort_values(
        ["momentum_score", "ret_20d", "ts_code"], ascending=[False, False, True], na_position="last"
    ).reset_index(drop=True)
    metrics["market_rank"] = np.arange(1, len(metrics) + 1)

    history_start = latest_date - pd.Timedelta(days=550)
    history = prices.loc[history_start:].stack(future_stack=True).rename("close_qfq").dropna().reset_index()
    history.columns = ["trade_date", "ts_code", "close_qfq"]

    breadth = metrics.groupby("healthcare_subindustry", as_index=False).agg(
        stock_count=("ts_code", "count"),
        median_momentum=("momentum_score", "median"),
        median_ret_20d=("ret_20d", "median"),
        median_ret_60d=("ret_60d", "median"),
        above_ma20_pct=("above_ma20", "mean"),
        above_ma60_pct=("above_ma60", "mean"),
        group_a_count=("group", lambda s: int((s == "A").sum())),
        overheated_count=("temperature", lambda s: int((s == "过热").sum())),
    )
    breadth["industry_rank"] = breadth["median_momentum"].rank(method="min", ascending=False).astype("Int64")
    breadth = breadth.sort_values("industry_rank")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(DATA_DIR / "momentum_snapshot.csv", index=False, encoding="utf-8-sig")
    history.to_csv(DATA_DIR / "price_history.csv.gz", index=False, compression="gzip")
    breadth.to_csv(DATA_DIR / "subindustry_snapshot.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "stock_count": int(len(metrics)),
        "subindustry_count": int(metrics["healthcare_subindustry"].nunique()),
        "price_history_start": history["trade_date"].min().strftime("%Y-%m-%d"),
        "methodology_version": "1.0.0",
    }
    (DATA_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built dashboard snapshot for {len(metrics)} stocks as of {metadata['as_of_date']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    build_snapshot(args.source_dir.resolve())
