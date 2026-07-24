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
OVERHEAT_THRESHOLD = 90


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True, na_option="keep")


def directional_state(ret_20d: pd.Series, ma60_gap: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [
                (ret_20d > 0) & (ma60_gap > 0),
                (ret_20d > 0) & (ma60_gap <= 0),
                (ret_20d <= 0) & (ma60_gap > 0),
            ],
            ["上涨", "修复", "转弱"],
            default="下跌",
        ),
        index=ret_20d.index,
        dtype="string",
    )


def combined_market_regime(frame: pd.DataFrame) -> pd.Series:
    market_up = frame["market_state"] == "上涨"
    healthcare_up = frame["healthcare_state"] == "上涨"
    healthcare_repair = frame["healthcare_state"] == "修复"
    return pd.Series(
        np.select(
            [
                market_up & healthcare_up,
                ~market_up & healthcare_up,
                market_up & ~healthcare_up,
                ~market_up & healthcare_repair,
            ],
            ["风险偏好", "医疗独立行情", "大盘独涨", "医疗修复"],
            default="防御状态",
        ),
        index=frame.index,
        dtype="string",
    )


def beta_bucket(percentiles: pd.Series) -> pd.Series:
    return pd.cut(
        percentiles,
        [-np.inf, 1 / 3, 2 / 3, np.inf],
        labels=["低Beta", "中Beta", "高Beta"],
        right=True,
    ).astype("string")


def positive_subindustry_percentile(frame: pd.DataFrame, column: str) -> pd.Series:
    """Rank positive valuation observations within each healthcare subindustry."""
    valid = frame[column].where(frame[column] > 0)
    return valid.groupby(frame["healthcare_subindustry"], dropna=False).transform(
        lambda values: values.rank(method="average", pct=True, na_option="keep")
    )


def trailing_return(prices: pd.DataFrame, sessions: int) -> pd.Series:
    if len(prices) <= sessions:
        return pd.Series(index=prices.columns, dtype=float)
    return prices.iloc[-1] / prices.iloc[-sessions - 1] - 1.0


def classify_temperature(row: pd.Series) -> str:
    if row["overheat_score"] >= OVERHEAT_THRESHOLD:
        return "过热"
    if row["overheat_score"] >= 60:
        return "偏热"
    if row["overheat_score"] >= 35:
        return "中性"
    return "偏冷"


def classify_group(row: pd.Series) -> str:
    enough_data = row["trading_days"] >= 121
    trend_confirmed = row["ret_20d"] > 0 and row["ret_60d"] > 0 and row["above_ma20"] and row["above_ma60"]
    if enough_data and row["momentum_score"] >= 70 and trend_confirmed and row["overheat_score"] < OVERHEAT_THRESHOLD:
        return "A"
    if enough_data and row["momentum_score"] >= 40 and row["ret_20d"] > -0.05:
        return "B"
    return "C"


def build_snapshot(source_dir: Path) -> None:
    universe_path = source_dir / "a_share_healthcare_universe.csv"
    prices_path = source_dir / "a_share_healthcare_prices_qfq_wide.csv"
    daily_basic_path = source_dir / "a_share_healthcare_daily_basic_long.csv"
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
    daily_returns = latest.pct_change(fill_method=None)
    metrics["volatility_20d"] = daily_returns.tail(20).std() * np.sqrt(252)

    benchmark = pd.read_csv(DATA_DIR / "market_benchmark.csv", parse_dates=["trade_date"])
    market_close = pd.to_numeric(
        benchmark.set_index("trade_date")["close"], errors="coerce"
    ).reindex(latest.index).ffill()
    market_returns = market_close.pct_change(fill_method=None)
    healthcare_returns = daily_returns.mean(axis=1, skipna=True)
    healthcare_close = (1 + healthcare_returns.fillna(0)).cumprod()
    trailing_stock_returns = daily_returns.tail(60)
    trailing_market_returns = market_returns.reindex(trailing_stock_returns.index)
    trailing_healthcare_returns = healthcare_returns.reindex(trailing_stock_returns.index)
    metrics["market_beta_60d"] = trailing_stock_returns.apply(
        lambda values: values.cov(trailing_market_returns)
    ).div(trailing_market_returns.var())
    metrics["healthcare_beta_60d"] = trailing_stock_returns.apply(
        lambda values: values.cov(trailing_healthcare_returns)
    ).div(trailing_healthcare_returns.var())
    metrics["market_beta_percentile"] = percentile(metrics["market_beta_60d"])
    metrics["healthcare_beta_percentile"] = percentile(metrics["healthcare_beta_60d"])
    metrics["market_beta_bucket"] = beta_bucket(metrics["market_beta_percentile"])
    metrics["healthcare_beta_bucket"] = beta_bucket(metrics["healthcare_beta_percentile"])
    metrics = metrics.reset_index()

    keep = [
        "ts_code", "name", "healthcare_subindustry", "classification_confidence", "market",
    ]
    metrics = metrics.merge(universe[keep], on="ts_code", how="left", validate="one_to_one")

    daily_basic = pd.read_csv(
        daily_basic_path,
        usecols=["ts_code", "trade_date", "total_mv", "turnover_rate", "pe_ttm", "pb"],
    )
    daily_basic["trade_date"] = pd.to_datetime(daily_basic["trade_date"], format="mixed", errors="coerce")
    daily_basic = daily_basic[
        daily_basic["ts_code"].isin(universe["ts_code"]) & (daily_basic["trade_date"] <= latest_date)
    ].copy()
    latest_basic = (
        daily_basic.sort_values(["ts_code", "trade_date"])
        .drop_duplicates("ts_code", keep="last")
        .rename(
            columns={
                "trade_date": "valuation_as_of_date",
                "turnover_rate": "latest_turnover_rate",
                "pe_ttm": "latest_pe_ttm",
                "pb": "latest_pb",
            }
        )
    )
    metrics = metrics.merge(latest_basic, on="ts_code", how="left", validate="one_to_one")
    # Tushare reports total_mv in RMB 10,000; dividing by 10,000 converts it to RMB 100m.
    metrics["market_cap_100m"] = pd.to_numeric(metrics["total_mv"], errors="coerce") / 1e4
    metrics["latest_pe_ttm"] = pd.to_numeric(metrics["latest_pe_ttm"], errors="coerce")
    metrics["latest_pb"] = pd.to_numeric(metrics["latest_pb"], errors="coerce")
    metrics["price_stale_days"] = (latest_date - pd.to_datetime(metrics["price_date"])).dt.days
    valuation_date = metrics["valuation_as_of_date"].max()
    metrics["pe_valid"] = metrics["latest_pe_ttm"] > 0
    metrics["pb_valid"] = metrics["latest_pb"] > 0
    metrics["pe_percentile_sub"] = positive_subindustry_percentile(metrics, "latest_pe_ttm")
    metrics["pb_percentile_sub"] = positive_subindustry_percentile(metrics, "latest_pb")
    pe_weight = metrics["pe_valid"].astype(float) * 0.60
    pb_weight = metrics["pb_valid"].astype(float) * 0.40
    valuation_weight = pe_weight + pb_weight
    value_raw = (
        (1 - metrics["pe_percentile_sub"].fillna(0)) * pe_weight
        + (1 - metrics["pb_percentile_sub"].fillna(0)) * pb_weight
    )
    metrics["valuation_score"] = (value_raw / valuation_weight * (0.75 + 0.25 * valuation_weight) * 100).where(valuation_weight > 0)
    metrics["valuation_status"] = np.select(
        [metrics["pe_valid"] & metrics["pb_valid"], metrics["pb_valid"]],
        ["PE+PB有效", "仅PB有效"],
        default="估值缺失",
    )
    metrics["valuation_coverage"] = valuation_weight

    return_cols = ["ret_5d", "ret_20d", "ret_60d", "ret_120d"]
    weights = {"ret_5d": 0.10, "ret_20d": 0.45, "ret_60d": 0.35}
    return_weight_total = sum(weights.values())
    for col in return_cols:
        metrics[f"{col}_market_pct"] = percentile(metrics[col])
        metrics[f"{col}_sub_pct"] = metrics.groupby("healthcare_subindustry", dropna=False)[col].transform(percentile)

    # Normalize the three scoring windows within their 90-point allocation so the
    # fixed formula has an exact theoretical maximum of 100 points.
    market_component = sum(
        metrics[f"{col}_market_pct"] * weight / return_weight_total
        for col, weight in weights.items()
    )
    sub_component = sum(
        metrics[f"{col}_sub_pct"] * weight / return_weight_total
        for col, weight in weights.items()
    )
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
    metrics["volatility_percentile"] = percentile(metrics["volatility_20d"]).fillna(1.0)
    metrics["stale_risk"] = metrics["price_stale_days"].clip(0, 30) / 30
    metrics["risk_score"] = (metrics["overheat_score"] * 0.70 + metrics["volatility_percentile"] * 100 * 0.20 + metrics["stale_risk"] * 100 * 0.10).clip(0, 100)
    metrics["data_completeness_score"] = (
        metrics["price_date"].notna().astype(float) * 0.55
        + metrics["valuation_coverage"].fillna(0).clip(0, 1) * 0.45
    ) * 100
    metrics["research_score"] = (
        metrics["momentum_score"] * 0.60
        + metrics["valuation_score"].fillna(50) * 0.25
        + (100 - metrics["risk_score"]) * 0.15
    ).clip(0, 100)
    metrics["temperature"] = metrics.apply(classify_temperature, axis=1)
    metrics["group"] = metrics.apply(classify_group, axis=1)
    metrics["signal_label"] = np.select(
        [
            (metrics["momentum_score"] >= 70) & (metrics["overheat_score"] < OVERHEAT_THRESHOLD),
            (metrics["momentum_score"] >= 70) & (metrics["overheat_score"] >= OVERHEAT_THRESHOLD),
            (metrics["valuation_score"] >= 70) & (metrics["momentum_score"] < 70),
        ],
        ["强趋势低过热", "强趋势高过热", "估值便宜待确认"],
        default="弱趋势/数据不足",
    )
    metrics["subindustry_rank"] = metrics.groupby("healthcare_subindustry")["momentum_score"].rank(method="min", ascending=False).astype("Int64")
    metrics["subindustry_count"] = metrics.groupby("healthcare_subindustry")["ts_code"].transform("count")
    metrics = metrics.sort_values(
        ["momentum_score", "ret_20d", "ts_code"], ascending=[False, False, True], na_position="last"
    ).reset_index(drop=True)
    metrics["market_rank"] = np.arange(1, len(metrics) + 1)

    history_start = latest_date - pd.Timedelta(days=550)
    history = prices.loc[history_start:].stack(future_stack=True).rename("close_qfq").dropna().reset_index()
    history.columns = ["trade_date", "ts_code", "close_qfq"]

    state_history = pd.DataFrame(
        {
            "trade_date": latest.index,
            "market_close": market_close.to_numpy(),
            "healthcare_close": healthcare_close.to_numpy(),
        }
    ).dropna(subset=["market_close", "healthcare_close"])
    for prefix in ["market", "healthcare"]:
        state_history[f"{prefix}_ret_20d"] = (
            state_history[f"{prefix}_close"]
            / state_history[f"{prefix}_close"].shift(20)
            - 1
        )
        state_history[f"{prefix}_ret_60d"] = (
            state_history[f"{prefix}_close"]
            / state_history[f"{prefix}_close"].shift(60)
            - 1
        )
        state_history[f"{prefix}_ma60_gap"] = (
            state_history[f"{prefix}_close"]
            / state_history[f"{prefix}_close"].rolling(60).mean()
            - 1
        )
        state_history[f"{prefix}_state"] = directional_state(
            state_history[f"{prefix}_ret_20d"],
            state_history[f"{prefix}_ma60_gap"],
        )
        state_history[f"{prefix}_normalized"] = (
            state_history[f"{prefix}_close"]
            / state_history[f"{prefix}_close"].iloc[0]
            * 100
        )
    state_history["market_regime"] = combined_market_regime(state_history)
    state_history = state_history[state_history["trade_date"] >= history_start].copy()
    current_state = state_history.iloc[-1]

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
    state_history.to_csv(
        DATA_DIR / "market_state_history.csv", index=False, encoding="utf-8-sig"
    )
    metadata = {
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "stock_count": int(len(metrics)),
        "subindustry_count": int(metrics["healthcare_subindustry"].nunique()),
        "price_history_start": history["trade_date"].min().strftime("%Y-%m-%d"),
        "valuation_as_of_date": valuation_date.strftime("%Y-%m-%d") if pd.notna(valuation_date) else None,
        "methodology_version": "1.7.0-trend-risk-market-beta",
        "market_state_definition": "20日收益率与相对MA60位置共同判断上涨、修复、转弱、下跌",
        "healthcare_benchmark": "当前310只医疗股票等权日收益指数",
        "current_market_state": current_state["market_state"],
        "current_healthcare_state": current_state["healthcare_state"],
        "current_market_regime": current_state["market_regime"],
    }
    (DATA_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built dashboard snapshot for {len(metrics)} stocks as of {metadata['as_of_date']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    build_snapshot(args.source_dir.resolve())
