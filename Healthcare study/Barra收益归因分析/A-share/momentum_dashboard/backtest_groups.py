#!/usr/bin/env python3
"""Backtest the simplified trend/drawdown-risk A/B/C labels without look-ahead data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from factor_research import (
    PRODUCTION_RISK_FACTORS,
    fit_ridge,
    load_panels,
    maximum_adverse_excursion,
    predict,
    score_percentile,
    snapshot_features,
)


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
DATA_DIR = APP_DIR / "data"
RISK_MODEL_HORIZON = 20
OVERHEAT_THRESHOLD = 90
LOOKBACK_YEARS = 3
BACKTEST_HORIZONS = (5, 20, 120)
BOOTSTRAP_SAMPLES = 10_000
TREND_BUCKET_ORDER = ["强趋势", "中趋势", "弱趋势"]
RISK_BUCKET_ORDER = ["低风险", "中风险", "高风险"]


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True, na_option="keep")


def trailing_return(prices: pd.DataFrame, position: int, sessions: int) -> pd.Series:
    return prices.iloc[position] / prices.iloc[position - sessions] - 1


def momentum_metrics(
    prices: pd.DataFrame,
    position: int,
    subindustry: pd.Series,
) -> pd.DataFrame:
    close = prices.iloc[position]
    metrics = pd.DataFrame(index=prices.columns)
    weights = {"ret_5d": 0.10, "ret_20d": 0.30, "ret_60d": 0.35, "ret_120d": 0.15}
    return_weight_total = sum(weights.values())
    for column, weight in weights.items():
        sessions = int(column.split("_")[1][:-1])
        metrics[column] = trailing_return(prices, position, sessions)
        metrics[f"{column}_market_pct"] = percentile(metrics[column])
        metrics[f"{column}_sub_pct"] = metrics[column].groupby(subindustry).rank(pct=True)

    ma20 = prices.iloc[position - 19 : position + 1].mean()
    high60 = prices.iloc[position - 59 : position + 1].max()
    metrics["ma20_gap"] = close / ma20 - 1
    metrics["drawdown_60d"] = close / high60 - 1
    market_component = sum(
        metrics[f"{column}_market_pct"] * weight / return_weight_total
        for column, weight in weights.items()
    )
    subindustry_component = sum(
        metrics[f"{column}_sub_pct"] * weight / return_weight_total
        for column, weight in weights.items()
    )
    trend_component = (
        metrics["ma20_gap"].clip(-0.20, 0.20).add(0.20).div(0.40) * 0.05
        + metrics["drawdown_60d"].clip(-0.30, 0).add(0.30).div(0.30) * 0.05
    )
    metrics["momentum_score"] = (
        market_component * 0.65 + subindustry_component * 0.25 + trend_component
    ).mul(100).clip(0, 100).fillna(0)
    return metrics


def classify_group(momentum_score: pd.Series, overheat_score: pd.Series) -> pd.Series:
    strong = momentum_score >= 70
    medium = momentum_score >= 40
    overheated = overheat_score >= OVERHEAT_THRESHOLD
    return pd.Series(
        np.select([strong & ~overheated, medium], ["A", "B"], default="C"),
        index=momentum_score.index,
    )


def classify_two_dimensions(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["trend_bucket"] = pd.cut(
        result["momentum_score"],
        [-np.inf, 40, 70, np.inf],
        labels=["弱趋势", "中趋势", "强趋势"],
        right=False,
    )
    result["risk_bucket"] = pd.cut(
        result["overheat_score"],
        [-np.inf, 30, 70, np.inf],
        labels=["低风险", "中风险", "高风险"],
        right=False,
    )
    return result


def two_dimension_summary(detail: pd.DataFrame, horizon: int) -> pd.DataFrame:
    classified = classify_two_dimensions(detail)
    period = (
        classified.groupby(
            ["entry_date", "trend_bucket", "risk_bucket"],
            observed=True,
            as_index=False,
        )
        .agg(
            average_forward_return=("forward_return", "mean"),
            average_forward_drawdown=("forward_drawdown", "mean"),
            stock_count=("ts_code", "count"),
        )
    )
    summary = (
        period.groupby(["trend_bucket", "risk_bucket"], observed=True, as_index=False)
        .agg(
            average_forward_return=("average_forward_return", "mean"),
            average_forward_drawdown=("average_forward_drawdown", "mean"),
            average_stock_count=("stock_count", "mean"),
            period_count=("entry_date", "nunique"),
        )
    )
    summary.insert(0, "horizon_sessions", horizon)
    summary["trend_bucket"] = summary["trend_bucket"].astype("string")
    summary["risk_bucket"] = summary["risk_bucket"].astype("string")
    return summary


def build_risk_training_panel(
    prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    market_returns: pd.Series,
    panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
) -> pd.DataFrame:
    panel_path = DATA_DIR / "survivorship_free_training_panel.csv.gz"
    if not panel_path.exists():
        raise FileNotFoundError(
            "Run test_survivorship_free_risk_model.py before rebuilding dashboard backtests"
        )
    return pd.read_csv(
        panel_path,
        parse_dates=["entry_date", "exit_date"],
    )


def historical_risk_score(
    position: int,
    prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    market_returns: pd.Series,
    panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
    training_panel: pd.DataFrame,
) -> tuple[pd.Series, pd.Timestamp, int]:
    entry_date = prices.index[position]
    train = training_panel[training_panel["exit_date"] <= entry_date].copy()
    if len(train) < 500:
        raise ValueError(f"Insufficient risk-model training data at {entry_date.date()}: {len(train)}")
    intercept, coefficients = fit_ridge(
        train, PRODUCTION_RISK_FACTORS, "forward_drawdown_loss"
    )
    current = snapshot_features(
        position, prices, daily_returns, market_returns, panels, universe_by_code
    )
    risk_score = score_percentile(
        predict(current, PRODUCTION_RISK_FACTORS, intercept, coefficients)
    )
    return risk_score, train["exit_date"].max(), int(train["entry_date"].nunique())


def portfolio_statistics(period_returns: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows = []
    for group, frame in period_returns.groupby("group", sort=True):
        frame = frame.sort_values("entry_date")
        returns = frame["average_forward_return"]
        equity = (1 + returns).cumprod()
        running_peak = equity.cummax()
        annualized_return = equity.iloc[-1] ** (252 / (horizon * len(returns))) - 1
        annualized_volatility = returns.std(ddof=1) * np.sqrt(252 / horizon)
        rows.append(
            {
                "group": group,
                "compound_return": equity.iloc[-1] - 1,
                "annualized_return": annualized_return,
                "annualized_volatility": annualized_volatility,
                "return_volatility_ratio": (
                    annualized_return / annualized_volatility
                    if annualized_volatility > 0
                    else np.nan
                ),
                "portfolio_max_drawdown": (equity / running_peak - 1).min(),
            }
        )
    return pd.DataFrame(rows)


def paired_spreads(period_returns: pd.DataFrame, horizon: int) -> pd.DataFrame:
    pivot = period_returns.pivot(index="entry_date", columns="group", values="average_forward_return")
    rng = np.random.default_rng(20260721 + horizon)
    rows = []
    for left, right in [("A", "B"), ("A", "C"), ("B", "C")]:
        difference = (pivot[left] - pivot[right]).dropna()
        if difference.empty:
            continue
        samples = rng.choice(
            difference.to_numpy(), size=(BOOTSTRAP_SAMPLES, len(difference)), replace=True
        ).mean(axis=1)
        rows.append(
            {
                "horizon_sessions": horizon,
                "spread": f"{left}-{right}",
                "mean_return_spread": difference.mean(),
                "median_return_spread": difference.median(),
                "positive_spread_rate": (difference > 0).mean(),
                "bootstrap_ci_low": np.quantile(samples, 0.025),
                "bootstrap_ci_high": np.quantile(samples, 0.975),
                "paired_period_count": len(difference),
            }
        )
    return pd.DataFrame(rows)


def backtest_horizon(
    prices: pd.DataFrame,
    raw_prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    market_returns: pd.Series,
    panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
    training_panel: pd.DataFrame,
    forward_sessions: int,
    risk_cache: dict[int, tuple[pd.Series, pd.Timestamp, int]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    last_entry_date = prices.index[-forward_sessions - 1]
    start_date = last_entry_date - pd.DateOffset(years=LOOKBACK_YEARS)
    first_position = max(120, int(prices.index.searchsorted(start_date)))
    last_position = len(prices) - forward_sessions - 1
    positions = list(range(last_position, first_position - 1, -forward_sessions))[::-1]
    subindustry = universe_by_code["healthcare_subindustry"]

    observations = []
    for sequence, position in enumerate(positions, start=1):
        metrics = momentum_metrics(prices, position, subindustry)
        if position not in risk_cache:
            risk_cache[position] = historical_risk_score(
                position,
                prices,
                daily_returns,
                market_returns,
                panels,
                universe_by_code,
                training_panel,
            )
        risk_score, training_end, training_periods = risk_cache[position]
        metrics["overheat_score"] = risk_score.reindex(metrics.index)
        metrics["group"] = classify_group(metrics["momentum_score"], metrics["overheat_score"])

        entry_close = prices.iloc[position]
        exit_close = prices.iloc[position + forward_sessions]
        future_return = exit_close / entry_close - 1
        future_path = prices.iloc[position + 1 : position + forward_sessions + 1].div(
            entry_close, axis=1
        ) - 1
        frame = metrics[["group", "momentum_score", "overheat_score"]].copy()
        frame["entry_date"] = prices.index[position]
        frame["exit_date"] = prices.index[position + forward_sessions]
        frame["risk_training_end"] = training_end
        frame["risk_training_periods"] = training_periods
        frame["forward_return"] = future_return
        frame["forward_drawdown"] = -maximum_adverse_excursion(future_path)
        frame["price_available"] = raw_prices.iloc[position].notna()
        frame.index.name = "ts_code"
        observations.append(frame.reset_index())
        if sequence % 25 == 0 or sequence == len(positions):
            print(
                f"{forward_sessions:>3}d: {sequence:>3}/{len(positions)} snapshots "
                f"through {prices.index[position].date()}"
            )

    detail = pd.concat(observations, ignore_index=True)
    detail = detail[detail["price_available"]].dropna(
        subset=["forward_return", "forward_drawdown", "overheat_score"]
    )
    period_returns = (
        detail.groupby(["entry_date", "exit_date", "group"], as_index=False)
        .agg(
            average_forward_return=("forward_return", "mean"),
            average_forward_drawdown=("forward_drawdown", "mean"),
            observation_count=("ts_code", "count"),
            average_momentum_score=("momentum_score", "mean"),
            average_overheat_score=("overheat_score", "mean"),
        )
    )
    universe_returns = detail.groupby("entry_date")["forward_return"].mean().rename(
        "universe_forward_return"
    )
    period_returns = period_returns.merge(universe_returns, on="entry_date", how="left")
    period_returns["forward_excess_return"] = (
        period_returns["average_forward_return"] - period_returns["universe_forward_return"]
    )
    summary = (
        period_returns.groupby("group", as_index=False)
        .agg(
            average_forward_return=("average_forward_return", "mean"),
            average_forward_excess_return=("forward_excess_return", "mean"),
            median_period_return=("average_forward_return", "median"),
            win_rate=("average_forward_return", lambda values: float((values > 0).mean())),
            excess_win_rate=("forward_excess_return", lambda values: float((values > 0).mean())),
            average_forward_drawdown=("average_forward_drawdown", "mean"),
            average_group_size=("observation_count", "mean"),
            average_momentum_score=("average_momentum_score", "mean"),
            average_overheat_score=("average_overheat_score", "mean"),
            rebalance_count=("entry_date", "nunique"),
        )
        .sort_values("group")
    )
    summary = summary.merge(
        detail.groupby("group")["ts_code"].count().rename("observation_count"),
        on="group",
        how="left",
    ).merge(portfolio_statistics(period_returns, forward_sessions), on="group", how="left")
    yearly = (
        period_returns.assign(year=period_returns["entry_date"].dt.year)
        .groupby(["year", "group"], as_index=False)
        .agg(
            average_forward_return=("average_forward_return", "mean"),
            win_rate=("average_forward_return", lambda values: float((values > 0).mean())),
            average_group_size=("observation_count", "mean"),
            rebalance_count=("entry_date", "nunique"),
        )
    )
    summary = summary.merge(
        yearly.groupby("group")["average_forward_return"].std().rename(
            "annual_average_dispersion"
        ),
        on="group",
        how="left",
    )
    summary.insert(0, "horizon_sessions", forward_sessions)
    yearly.insert(1, "horizon_sessions", forward_sessions)
    spreads = paired_spreads(period_returns, forward_sessions)
    metadata = {
        "start_entry_date": detail["entry_date"].min().strftime("%Y-%m-%d"),
        "end_entry_date": detail["entry_date"].max().strftime("%Y-%m-%d"),
        "last_exit_date": detail["exit_date"].max().strftime("%Y-%m-%d"),
        "forward_sessions": forward_sessions,
        "rebalance_sessions": forward_sessions,
        "rebalance_count": int(detail["entry_date"].nunique()),
        "observation_count": int(len(detail)),
    }
    return summary, yearly, spreads, detail, metadata


def build_backtest(
    source_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    universe, close, panels, benchmark_close = load_panels(source_dir)
    raw_prices = close.copy()
    prices = close.ffill(limit=3)
    daily_returns = prices.pct_change(fill_method=None)
    market_returns = benchmark_close.pct_change(fill_method=None)
    universe_by_code = universe.set_index("ts_code")
    print("Building the historical 20-day risk-model training panel...")
    training_panel = build_risk_training_panel(
        prices, daily_returns, market_returns, panels, universe_by_code
    )
    risk_cache: dict[int, tuple[pd.Series, pd.Timestamp, int]] = {}
    results = [
        backtest_horizon(
            prices,
            raw_prices,
            daily_returns,
            market_returns,
            panels,
            universe_by_code,
            training_panel,
            horizon,
            risk_cache,
        )
        for horizon in BACKTEST_HORIZONS
    ]
    summary = pd.concat([result[0] for result in results], ignore_index=True)
    yearly = pd.concat([result[1] for result in results], ignore_index=True)
    spreads = pd.concat([result[2] for result in results], ignore_index=True)
    detail = pd.concat(
        [result[3].assign(horizon_sessions=horizon) for horizon, result in zip(BACKTEST_HORIZONS, results)],
        ignore_index=True,
    )
    two_dimensions = pd.concat(
        [
            two_dimension_summary(result[3], horizon)
            for horizon, result in zip(BACKTEST_HORIZONS, results)
        ],
        ignore_index=True,
    )
    metadata = {
        "methodology_version": "fixed_100_point_trend_plus_survivorship_free_7factor_mae_risk_v4",
        "lookback_years": LOOKBACK_YEARS,
        "risk_model_horizon": RISK_MODEL_HORIZON,
        "risk_model": "动态申万历史7因子-Ridge",
        "risk_training_rule": "每个建仓日仅使用该日前已完成20日持有期的动态申万医疗历史成员样本滚动重训",
        "risk_target_definition": "max(0, -min(未来持有期收益路径))；价格从未跌破建仓价时记为0",
        "trend_score_definition": "固定理论满分100分；5/20/60/120日收益率分别贡献10/30/35/15分（其中全市场排名合计65分、子行业排名合计25分），MA20与60日高点位置各5分",
        "overheat_definition": "20日最大不利波动（MAE）风险预测横截面百分位不低于90",
        "group_rules": {
            "A": "趋势分>=70且过热分<90",
            "B": "趋势分>=40但不满足A",
            "C": "趋势分<40",
        },
        "execution": "建仓日收盘形成信号并按该收盘价成交",
        "weighting": "每期组内等权，再对各调仓期等权平均",
        "horizons": {
            str(horizon): result[4] for horizon, result in zip(BACKTEST_HORIZONS, results)
        },
        "universe_note": "风险模型训练使用调仓日有效的申万医药生物历史成员，包含退市及被剔除股票；收益矩阵的展示股票仍为当前310只广义医疗股票。",
    }
    return summary, yearly, spreads, detail, two_dimensions, metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    summary_frame, yearly_frame, spreads_frame, detail_frame, two_dimensions_frame, meta = build_backtest(
        args.source_dir.resolve()
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary_frame.to_csv(DATA_DIR / "group_backtest_summary.csv", index=False, encoding="utf-8-sig")
    yearly_frame.to_csv(DATA_DIR / "group_backtest_yearly.csv", index=False, encoding="utf-8-sig")
    spreads_frame.to_csv(DATA_DIR / "group_backtest_spreads.csv", index=False, encoding="utf-8-sig")
    detail_frame.to_csv(
        DATA_DIR / "group_backtest_detail.csv.gz", index=False, compression="gzip", encoding="utf-8"
    )
    two_dimensions_frame.to_csv(
        DATA_DIR / "two_dimension_backtest.csv", index=False, encoding="utf-8-sig"
    )
    (DATA_DIR / "group_backtest_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary_frame.to_string(index=False))
    print("\nPaired return spreads:")
    print(spreads_frame.to_string(index=False))
