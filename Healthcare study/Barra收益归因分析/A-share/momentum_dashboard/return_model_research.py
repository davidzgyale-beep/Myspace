#!/usr/bin/env python3
"""Research regime-aware return models on a point-in-time SW healthcare universe."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
CACHE_DIR = DATA_DIR / "survivorship_free_cache"
START_DATE = "20190101"
END_DATE = "20260720"
OOS_START_YEAR = 2023
HORIZONS = (5, 20)
RIDGE_ALPHA = 100.0
MIN_TRAINING_OBSERVATIONS = 2_000

MARKET_BENCHMARK = "000300.SH"
PRIMARY_HEALTHCARE_BENCHMARK = "000808.CSI"
ETF_HEALTHCARE_BENCHMARK = "159938.SZ"

TREND_FACTORS = [
    "stock_return_5d",
    "stock_return_20d",
    "stock_return_60_ex_20d",
    "stock_ma20_gap",
    "stock_ma60_gap",
]
STATE_BETA_FACTORS = [
    "market_beta_60d",
    "healthcare_beta_60d",
    "market_return_20d",
    "healthcare_return_20d",
    "healthcare_relative_20d",
    "market_ma60_gap",
    "healthcare_ma60_gap",
]
INTERACTION_FACTORS = [
    "market_beta_x_market_return",
    "healthcare_beta_x_healthcare_return",
    "healthcare_beta_x_relative_strength",
    "market_beta_x_market_ma60",
    "healthcare_beta_x_healthcare_ma60",
]
IDIOSYNCRATIC_FACTORS = [
    "market_beta_change_60d",
    "healthcare_beta_change_60d",
    "residual_momentum_20d",
    "residual_volatility_60d",
    "two_factor_r_squared_60d",
]

MODEL_FACTORS = {
    "1. 趋势基线": TREND_FACTORS,
    "2. 指数状态+双Beta": STATE_BETA_FACTORS,
    "3. 状态+双Beta+交互项": STATE_BETA_FACTORS + INTERACTION_FACTORS,
    "4. 交互项+残差动量+Beta变化": (
        STATE_BETA_FACTORS + INTERACTION_FACTORS + IDIOSYNCRATIC_FACTORS
    ),
}

FACTOR_LABELS = {
    "stock_return_5d": "个股5日收益",
    "stock_return_20d": "个股20日收益",
    "stock_return_60_ex_20d": "个股60日剔除近20日收益",
    "stock_ma20_gap": "个股距MA20",
    "stock_ma60_gap": "个股距MA60",
    "market_beta_60d": "60日大盘Beta",
    "healthcare_beta_60d": "60日医药Beta",
    "market_return_20d": "沪深300 20日收益",
    "healthcare_return_20d": "医药指数20日收益",
    "healthcare_relative_20d": "医药相对大盘20日强弱",
    "market_ma60_gap": "沪深300距MA60",
    "healthcare_ma60_gap": "医药指数距MA60",
    "market_beta_x_market_return": "大盘Beta×沪深300趋势",
    "healthcare_beta_x_healthcare_return": "医药Beta×医药趋势",
    "healthcare_beta_x_relative_strength": "医药Beta×医药相对强弱",
    "market_beta_x_market_ma60": "大盘Beta×大盘MA60位置",
    "healthcare_beta_x_healthcare_ma60": "医药Beta×医药MA60位置",
    "market_beta_change_60d": "大盘Beta近期变化",
    "healthcare_beta_change_60d": "医药Beta近期变化",
    "residual_momentum_20d": "20日残差动量",
    "residual_volatility_60d": "60日残差波动率",
    "two_factor_r_squared_60d": "双因子拟合度R²",
}


def load_tushare_query():
    path = SOURCE_DIR / "build_a_share_healthcare_universe.py"
    spec = importlib.util.spec_from_file_location("healthcare_universe_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.tushare_query


def fetch_benchmarks() -> pd.DataFrame:
    query = load_tushare_query()
    requests = [
        ("index_daily", MARKET_BENCHMARK, "沪深300"),
        ("index_daily", PRIMARY_HEALTHCARE_BENCHMARK, "中证申万医药生物指数"),
        ("fund_daily", ETF_HEALTHCARE_BENCHMARK, "广发中证全指医药卫生ETF"),
    ]
    rows = []
    for api_name, code, name in requests:
        frame = query(
            api_name,
            ts_code=code,
            start_date=START_DATE,
            end_date=END_DATE,
            fields="ts_code,trade_date,close",
        )
        if frame.empty:
            raise RuntimeError(f"Benchmark returned no observations: {code}")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["benchmark_name"] = name
        rows.append(frame[["trade_date", "ts_code", "benchmark_name", "close"]])
    result = pd.concat(rows, ignore_index=True).sort_values(["trade_date", "ts_code"])
    result.to_csv(DATA_DIR / "return_model_benchmarks.csv", index=False, encoding="utf-8-sig")
    return result


def load_membership() -> pd.DataFrame:
    frame = pd.read_csv(CACHE_DIR / "sw_healthcare_l1_membership.csv")
    frame["in_date"] = pd.to_datetime(
        frame["in_date"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    frame["out_date"] = pd.to_datetime(
        frame["out_date"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    start = pd.Timestamp(START_DATE)
    end = pd.Timestamp(END_DATE)
    return frame[
        frame["in_date"].le(end)
        & (frame["out_date"].isna() | frame["out_date"].ge(start))
    ].copy()


def load_stock_closes(membership: pd.DataFrame) -> pd.DataFrame:
    local = pd.read_csv(
        SOURCE_DIR / "a_share_healthcare_prices_long.csv",
        usecols=["ts_code", "trade_date", "close_qfq"],
        parse_dates=["trade_date"],
    )
    # Keep the current 310-stock display set for live scoring, even when a stock is
    # outside the point-in-time SW training universe.
    codes = set(membership["con_code"]) | set(local["ts_code"])
    cached = []
    local_codes = set(local["ts_code"])
    for code in sorted(codes - local_codes):
        path = CACHE_DIR / "prices" / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing point-in-time price cache: {path}")
        cached.append(
            pd.read_csv(
                path,
                usecols=["ts_code", "trade_date", "close_qfq"],
                parse_dates=["trade_date"],
            )
        )
    long = pd.concat([local, *cached], ignore_index=True)
    long["close_qfq"] = pd.to_numeric(long["close_qfq"], errors="coerce")
    long = long.drop_duplicates(["ts_code", "trade_date"], keep="last")
    close = long.pivot(index="trade_date", columns="ts_code", values="close_qfq").sort_index()
    return close.reindex(columns=sorted(codes))


def active_membership_mask(dates: pd.DatetimeIndex, membership: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(False, index=dates, columns=sorted(membership["con_code"].unique()))
    for row in membership.itertuples():
        end = row.out_date if pd.notna(row.out_date) else dates.max()
        result.loc[(dates >= row.in_date) & (dates <= end), row.con_code] = True
    return result


def rolling_state_zscore(series: pd.Series, window: int = 756) -> pd.Series:
    minimum = 120
    mean = series.rolling(window, min_periods=minimum).mean()
    std = series.rolling(window, min_periods=minimum).std()
    return ((series - mean) / std).clip(-3, 3)


def cross_section_zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    median = values.median()
    mad = (values - median).abs().median()
    if pd.notna(mad) and mad > 0:
        values = values.clip(median - 4 * 1.4826 * mad, median + 4 * 1.4826 * mad)
    std = values.std()
    return (values - values.mean()) / std if pd.notna(std) and std > 0 else values * np.nan


def covariance_beta(stock_returns: pd.DataFrame, benchmark: pd.Series) -> pd.Series:
    return stock_returns.apply(lambda values: values.cov(benchmark)).div(benchmark.var())


def residual_statistics(
    stock_returns: pd.DataFrame,
    market_returns: pd.Series,
    healthcare_returns: pd.Series,
) -> pd.DataFrame:
    result = pd.DataFrame(index=stock_returns.columns)
    for code in stock_returns:
        sample = pd.concat(
            [stock_returns[code], market_returns, healthcare_returns], axis=1
        ).dropna()
        if len(sample) < 40:
            continue
        y = sample.iloc[:, 0].to_numpy(float)
        x = np.column_stack([np.ones(len(sample)), sample.iloc[:, 1:].to_numpy(float)])
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
        residual = y - x @ coefficients
        total = np.square(y - y.mean()).sum()
        result.loc[code, "market_beta_60d"] = coefficients[1]
        result.loc[code, "healthcare_beta_60d"] = coefficients[2]
        result.loc[code, "residual_momentum_20d"] = np.prod(1 + residual[-20:]) - 1
        result.loc[code, "residual_volatility_60d"] = np.std(residual, ddof=1) * np.sqrt(252)
        result.loc[code, "two_factor_r_squared_60d"] = (
            1 - np.square(residual).sum() / total if total > 0 else np.nan
        )
    return result


def two_factor_betas(
    stock_returns: pd.DataFrame,
    market_returns: pd.Series,
    healthcare_returns: pd.Series,
) -> pd.DataFrame:
    result = pd.DataFrame(index=stock_returns.columns)
    for code in stock_returns:
        sample = pd.concat(
            [stock_returns[code], market_returns, healthcare_returns], axis=1
        ).dropna()
        if len(sample) < 40:
            continue
        y = sample.iloc[:, 0].to_numpy(float)
        x = np.column_stack([np.ones(len(sample)), sample.iloc[:, 1:].to_numpy(float)])
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
        result.loc[code, "market_beta_60d"] = coefficients[1]
        result.loc[code, "healthcare_beta_60d"] = coefficients[2]
    return result


def market_regime(
    market_return: float,
    healthcare_return: float,
    market_ma60_gap: float,
    healthcare_ma60_gap: float,
) -> str:
    market_up = market_return > 0 and market_ma60_gap > 0
    healthcare_up = healthcare_return > 0 and healthcare_ma60_gap > 0
    if market_up and healthcare_up:
        return "风险偏好"
    if healthcare_up:
        return "医疗独立行情"
    if market_up:
        return "大盘独涨"
    return "防御/修复"


def build_panels(
    refresh_benchmarks: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.Series]]:
    membership = load_membership()
    close_raw = load_stock_closes(membership)
    benchmarks_path = DATA_DIR / "return_model_benchmarks.csv"
    benchmarks = (
        fetch_benchmarks()
        if refresh_benchmarks or not benchmarks_path.exists()
        else pd.read_csv(benchmarks_path, parse_dates=["trade_date"])
    )
    benchmark_close = benchmarks.pivot(index="trade_date", columns="ts_code", values="close")
    dates = close_raw.index.intersection(benchmark_close.index).sort_values()
    close_raw = close_raw.reindex(dates)
    benchmark_close = benchmark_close.reindex(dates).ffill()
    membership_mask = (
        active_membership_mask(dates, membership)
        .reindex(columns=close_raw.columns)
        .fillna(False)
        .astype(bool)
    )
    close = close_raw.ffill()
    returns = close.pct_change(fill_method=None)
    dynamic_equal_return = returns.where(membership_mask).mean(axis=1, skipna=True)
    healthcare_benchmarks = {
        "动态申万成分等权": (1 + dynamic_equal_return.fillna(0)).cumprod() * 100,
        "中证申万医药生物指数": benchmark_close[PRIMARY_HEALTHCARE_BENCHMARK],
        "中证全指医药卫生ETF": benchmark_close[ETF_HEALTHCARE_BENCHMARK],
    }
    return close, membership_mask, benchmark_close[[MARKET_BENCHMARK]], healthcare_benchmarks


def build_feature_panel(
    close: pd.DataFrame,
    membership_mask: pd.DataFrame,
    market_close: pd.Series,
    healthcare_close: pd.Series,
    horizon: int,
    current_codes: list[str],
) -> pd.DataFrame:
    returns = close.pct_change(fill_method=None)
    market_returns = market_close.pct_change(fill_method=None)
    healthcare_returns = healthcare_close.pct_change(fill_method=None)
    market_ret20 = market_close / market_close.shift(20) - 1
    healthcare_ret20 = healthcare_close / healthcare_close.shift(20) - 1
    market_gap60 = market_close / market_close.rolling(60).mean() - 1
    healthcare_gap60 = healthcare_close / healthcare_close.rolling(60).mean() - 1
    state_series = {
        "market_return_20d": rolling_state_zscore(market_ret20),
        "healthcare_return_20d": rolling_state_zscore(healthcare_ret20),
        "healthcare_relative_20d": rolling_state_zscore(healthcare_ret20 - market_ret20),
        "market_ma60_gap": rolling_state_zscore(market_gap60),
        "healthcare_ma60_gap": rolling_state_zscore(healthcare_gap60),
    }
    positions = list(range(120, len(close) - horizon, horizon))
    if positions[-1] != len(close) - 1:
        positions.append(len(close) - 1)
    rows = []
    for number, position in enumerate(positions, 1):
        entry_date = close.index[position]
        if position == len(close) - 1:
            codes = pd.Index([code for code in current_codes if code in close.columns])
        else:
            eligible = membership_mask.iloc[position]
            codes = eligible[eligible].index
        entry = close.iloc[position].reindex(codes)
        sufficient = close.iloc[position - 59 : position + 1].reindex(columns=codes).notna().sum() >= 40
        codes = sufficient[sufficient].index
        entry = entry.reindex(codes)
        trailing = returns.iloc[position - 59 : position + 1].reindex(columns=codes)
        previous = returns.iloc[position - 119 : position - 59].reindex(columns=codes)
        trailing_market = market_returns.iloc[position - 59 : position + 1]
        trailing_healthcare = healthcare_returns.iloc[position - 59 : position + 1]
        previous_market = market_returns.iloc[position - 119 : position - 59]
        previous_healthcare = healthcare_returns.iloc[position - 119 : position - 59]

        stats = residual_statistics(trailing, trailing_market, trailing_healthcare)
        previous_betas = two_factor_betas(
            previous, previous_market, previous_healthcare
        )
        stats["market_beta_change_60d"] = (
            stats["market_beta_60d"] - previous_betas["market_beta_60d"]
        )
        stats["healthcare_beta_change_60d"] = (
            stats["healthcare_beta_60d"] - previous_betas["healthcare_beta_60d"]
        )
        stats["stock_return_5d"] = entry / close.iloc[position - 5].reindex(codes) - 1
        stats["stock_return_20d"] = entry / close.iloc[position - 20].reindex(codes) - 1
        stats["stock_return_60_ex_20d"] = (
            close.iloc[position - 20].reindex(codes)
            / close.iloc[position - 60].reindex(codes)
            - 1
        )
        stats["stock_ma20_gap"] = entry / close.iloc[position - 19 : position + 1].mean().reindex(codes) - 1
        stats["stock_ma60_gap"] = entry / close.iloc[position - 59 : position + 1].mean().reindex(codes) - 1
        for factor in [
            *TREND_FACTORS,
            "market_beta_60d",
            "healthcare_beta_60d",
            *IDIOSYNCRATIC_FACTORS,
        ]:
            stats[factor] = cross_section_zscore(stats[factor])
        for factor, series in state_series.items():
            stats[factor] = series.iloc[position]

        stats["market_beta_x_market_return"] = (
            stats["market_beta_60d"] * stats["market_return_20d"]
        )
        stats["healthcare_beta_x_healthcare_return"] = (
            stats["healthcare_beta_60d"] * stats["healthcare_return_20d"]
        )
        stats["healthcare_beta_x_relative_strength"] = (
            stats["healthcare_beta_60d"] * stats["healthcare_relative_20d"]
        )
        stats["market_beta_x_market_ma60"] = (
            stats["market_beta_60d"] * stats["market_ma60_gap"]
        )
        stats["healthcare_beta_x_healthcare_ma60"] = (
            stats["healthcare_beta_60d"] * stats["healthcare_ma60_gap"]
        )
        if position + horizon < len(close):
            future_stock = close.iloc[position + horizon].reindex(codes).div(entry) - 1
            future_healthcare = (
                healthcare_close.iloc[position + horizon] / healthcare_close.iloc[position] - 1
            )
            stats["forward_return"] = future_stock
            stats["forward_relative_return"] = future_stock - future_healthcare
            exit_date = close.index[position + horizon]
        else:
            stats["forward_return"] = np.nan
            stats["forward_relative_return"] = np.nan
            exit_date = pd.NaT
        stats["entry_date"] = entry_date
        stats["exit_date"] = exit_date
        stats["market_regime"] = market_regime(
            market_ret20.iloc[position],
            healthcare_ret20.iloc[position],
            market_gap60.iloc[position],
            healthcare_gap60.iloc[position],
        )
        stats.index.name = "ts_code"
        rows.append(stats.reset_index())
        if number % 20 == 0:
            print(f"horizon={horizon}: built {number} entry dates", flush=True)
    return pd.concat(rows, ignore_index=True)


def fit_ridge(
    train: pd.DataFrame,
    factors: list[str],
    target: str,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    x = train[factors].replace([np.inf, -np.inf], np.nan)
    means = x.mean().to_numpy(float)
    stds = x.std().replace(0, 1).fillna(1).to_numpy(float)
    x_values = (x.fillna(pd.Series(means, index=factors)).to_numpy(float) - means) / stds
    y = train[target].to_numpy(float)
    valid = np.isfinite(y)
    x_values = x_values[valid]
    y_frame = train.loc[valid, ["entry_date", target]].copy()
    y = y[valid] - y_frame.groupby("entry_date")[target].transform("mean").to_numpy(float)
    design = np.column_stack([np.ones(len(x_values)), x_values])
    penalty = np.eye(design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return float(coefficients[0]), coefficients[1:], means, stds


def predict(
    frame: pd.DataFrame,
    factors: list[str],
    fitted: tuple[float, np.ndarray, np.ndarray, np.ndarray],
) -> pd.Series:
    intercept, coefficients, means, stds = fitted
    x = frame[factors].replace([np.inf, -np.inf], np.nan)
    values = (x.fillna(pd.Series(means, index=factors)).to_numpy(float) - means) / stds
    return pd.Series(intercept + values @ coefficients, index=frame.index)


def assign_deciles(series: pd.Series) -> pd.Series:
    valid = series.notna()
    result = pd.Series(np.nan, index=series.index)
    if valid.sum() >= 30:
        result.loc[valid] = pd.qcut(
            series.loc[valid].rank(method="first"), 10, labels=False
        ) + 1
    return result


def period_metrics(frame: pd.DataFrame, prediction: str) -> pd.DataFrame:
    rows = []
    for date, period in frame.groupby("entry_date", sort=True):
        valid = period[[prediction, "forward_relative_return"]].dropna()
        if len(valid) < 30:
            continue
        ic = valid[prediction].rank().corr(valid["forward_relative_return"].rank())
        decile = assign_deciles(valid[prediction])
        top = valid.loc[decile == 10, "forward_relative_return"].mean()
        bottom = valid.loc[decile == 1, "forward_relative_return"].mean()
        rows.append(
            {
                "entry_date": date,
                "rank_ic": ic,
                "top_decile_relative_return": top,
                "bottom_decile_relative_return": bottom,
                "top_bottom_spread": top - bottom,
                "stock_count": len(valid),
                "market_regime": period["market_regime"].iloc[0],
            }
        )
    return pd.DataFrame(rows)


def evaluate_models(
    panel: pd.DataFrame,
    horizon: int,
    benchmark_name: str,
    models: dict[str, list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail_rows = []
    coefficient_rows = []
    for year in range(OOS_START_YEAR, panel["entry_date"].dt.year.max() + 1):
        cutoff = pd.Timestamp(f"{year}-01-01")
        train = panel[panel["exit_date"] < cutoff]
        test = panel[panel["entry_date"].dt.year == year].copy()
        if len(train) < MIN_TRAINING_OBSERVATIONS or test.empty:
            continue
        for model, factors in models.items():
            fitted = fit_ridge(train, factors, "forward_relative_return")
            prediction = f"prediction_{len(detail_rows)}"
            test[prediction] = predict(test, factors, fitted)
            metrics = period_metrics(test, prediction)
            metrics["test_year"] = year
            metrics["horizon_sessions"] = horizon
            metrics["healthcare_benchmark"] = benchmark_name
            metrics["model"] = model
            detail_rows.append(metrics)
            for factor, coefficient in zip(factors, fitted[1]):
                coefficient_rows.append(
                    {
                        "test_year": year,
                        "horizon_sessions": horizon,
                        "healthcare_benchmark": benchmark_name,
                        "model": model,
                        "factor": factor,
                        "factor_label": FACTOR_LABELS[factor],
                        "standardized_coefficient": coefficient,
                    }
                )
    detail = pd.concat(detail_rows, ignore_index=True)
    yearly = (
        detail.groupby(
            ["healthcare_benchmark", "horizon_sessions", "model", "test_year"],
            as_index=False,
        )
        .agg(
            mean_rank_ic=("rank_ic", "mean"),
            positive_ic_rate=("rank_ic", lambda values: (values > 0).mean()),
            top_bottom_spread=("top_bottom_spread", "mean"),
            spread_win_rate=("top_bottom_spread", lambda values: (values > 0).mean()),
            rebalance_count=("entry_date", "nunique"),
        )
    )
    summary = (
        detail.groupby(
            ["healthcare_benchmark", "horizon_sessions", "model"], as_index=False
        )
        .agg(
            mean_rank_ic=("rank_ic", "mean"),
            rank_ic_std=("rank_ic", "std"),
            positive_ic_rate=("rank_ic", lambda values: (values > 0).mean()),
            top_decile_relative_return=("top_decile_relative_return", "mean"),
            bottom_decile_relative_return=("bottom_decile_relative_return", "mean"),
            top_bottom_spread=("top_bottom_spread", "mean"),
            spread_win_rate=("top_bottom_spread", lambda values: (values > 0).mean()),
            rebalance_count=("entry_date", "nunique"),
            average_stock_count=("stock_count", "mean"),
        )
    )
    summary["rank_ic_t_stat"] = summary["mean_rank_ic"] / (
        summary["rank_ic_std"] / np.sqrt(summary["rebalance_count"])
    )
    regime = (
        detail.groupby(
            [
                "healthcare_benchmark",
                "horizon_sessions",
                "model",
                "market_regime",
            ],
            as_index=False,
        )
        .agg(
            mean_rank_ic=("rank_ic", "mean"),
            positive_ic_rate=("rank_ic", lambda values: (values > 0).mean()),
            top_bottom_spread=("top_bottom_spread", "mean"),
            spread_win_rate=("top_bottom_spread", lambda values: (values > 0).mean()),
            rebalance_count=("entry_date", "nunique"),
        )
    )
    return summary, yearly, detail, pd.DataFrame(coefficient_rows), regime


def bootstrap_mean_interval(values: pd.Series, seed: int) -> tuple[float, float]:
    sample = values.dropna().to_numpy(float)
    if len(sample) < 10:
        return np.nan, np.nan
    generator = np.random.default_rng(seed)
    draws = generator.choice(sample, size=(5_000, len(sample)), replace=True).mean(axis=1)
    lower, upper = np.quantile(draws, [0.025, 0.975])
    return float(lower), float(upper)


def paired_model_comparison(period_detail: pd.DataFrame) -> pd.DataFrame:
    primary = period_detail[
        period_detail["healthcare_benchmark"] == "中证申万医药生物指数"
    ]
    baseline_name = "1. 趋势基线"
    rows = []
    for horizon, horizon_frame in primary.groupby("horizon_sessions"):
        baseline = horizon_frame[horizon_frame["model"] == baseline_name].set_index(
            "entry_date"
        )
        for number, (model, candidate) in enumerate(
            horizon_frame.groupby("model", sort=False), 1
        ):
            if model == baseline_name:
                continue
            paired = candidate.set_index("entry_date").join(
                baseline[["rank_ic", "top_bottom_spread"]],
                how="inner",
                lsuffix="_candidate",
                rsuffix="_baseline",
            )
            delta_ic = paired["rank_ic_candidate"] - paired["rank_ic_baseline"]
            delta_spread = (
                paired["top_bottom_spread_candidate"]
                - paired["top_bottom_spread_baseline"]
            )
            ic_low, ic_high = bootstrap_mean_interval(delta_ic, 1000 + number + horizon)
            spread_low, spread_high = bootstrap_mean_interval(
                delta_spread, 2000 + number + horizon
            )
            rows.append(
                {
                    "horizon_sessions": horizon,
                    "candidate_model": model,
                    "baseline_model": baseline_name,
                    "paired_period_count": len(paired),
                    "mean_delta_rank_ic": delta_ic.mean(),
                    "delta_rank_ic_ci_low": ic_low,
                    "delta_rank_ic_ci_high": ic_high,
                    "delta_rank_ic_positive_rate": (delta_ic > 0).mean(),
                    "mean_delta_top_bottom_spread": delta_spread.mean(),
                    "delta_spread_ci_low": spread_low,
                    "delta_spread_ci_high": spread_high,
                    "delta_spread_positive_rate": (delta_spread > 0).mean(),
                }
            )
    return pd.DataFrame(rows)


def score_current_panel(
    panel: pd.DataFrame,
    display_codes: list[str],
    horizon: int,
    benchmark_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors = MODEL_FACTORS["4. 交互项+残差动量+Beta变化"]
    current_date = panel["entry_date"].max()
    current = panel[panel["entry_date"] == current_date].copy()
    train = panel[panel["exit_date"] <= current_date]
    fitted = fit_ridge(train, factors, "forward_relative_return")
    current["predicted_relative_return"] = predict(current, factors, fitted)
    current["return_model_score"] = (
        current["predicted_relative_return"].rank(method="average", pct=True) * 100
    )
    scores = current[current["ts_code"].isin(display_codes)][
        ["ts_code", "entry_date", "market_regime", "predicted_relative_return", "return_model_score"]
    ].copy()
    scores["horizon_sessions"] = horizon
    scores["healthcare_benchmark"] = benchmark_name
    scores["model"] = "4. 交互项+残差动量+Beta变化"
    coefficients = pd.DataFrame(
        {
            "horizon_sessions": horizon,
            "healthcare_benchmark": benchmark_name,
            "factor": factors,
            "factor_label": [FACTOR_LABELS[factor] for factor in factors],
            "standardized_coefficient": fitted[1],
        }
    )
    return scores, coefficients


def run(refresh_benchmarks: bool) -> None:
    close, membership_mask, market_frame, healthcare_benchmarks = build_panels(
        refresh_benchmarks
    )
    display_codes = pd.read_csv(
        SOURCE_DIR / "a_share_healthcare_universe.csv", usecols=["ts_code"]
    )["ts_code"].tolist()
    primary_name = "中证申万医药生物指数"
    summaries = []
    yearly_frames = []
    period_frames = []
    coefficient_frames = []
    regime_frames = []
    current_scores = []
    current_coefficients = []
    panels: dict[tuple[str, int], pd.DataFrame] = {}

    for benchmark_name, healthcare_close in healthcare_benchmarks.items():
        models = MODEL_FACTORS if benchmark_name == primary_name else {
            "4. 交互项+残差动量+Beta变化": MODEL_FACTORS[
                "4. 交互项+残差动量+Beta变化"
            ]
        }
        for horizon in HORIZONS:
            panel = build_feature_panel(
                close,
                membership_mask,
                market_frame[MARKET_BENCHMARK],
                healthcare_close.reindex(close.index).ffill(),
                horizon,
                display_codes,
            )
            panels[(benchmark_name, horizon)] = panel
            summary, yearly, periods, coefficients, regime = evaluate_models(
                panel, horizon, benchmark_name, models
            )
            summaries.append(summary)
            yearly_frames.append(yearly)
            period_frames.append(periods)
            coefficient_frames.append(coefficients)
            regime_frames.append(regime)
            if benchmark_name == primary_name:
                scores, production_coefficients = score_current_panel(
                    panel, display_codes, horizon, benchmark_name
                )
                current_scores.append(scores)
                current_coefficients.append(production_coefficients)

    outputs = {
        "return_model_summary.csv": pd.concat(summaries, ignore_index=True),
        "return_model_yearly.csv": pd.concat(yearly_frames, ignore_index=True),
        "return_model_period_detail.csv": pd.concat(period_frames, ignore_index=True),
        "return_model_coefficients.csv": pd.concat(coefficient_frames, ignore_index=True),
        "return_model_regime.csv": pd.concat(regime_frames, ignore_index=True),
        "return_model_current_scores.csv": pd.concat(current_scores, ignore_index=True),
        "return_model_current_coefficients.csv": pd.concat(
            current_coefficients, ignore_index=True
        ),
    }
    outputs["return_model_paired_comparison.csv"] = paired_model_comparison(
        outputs["return_model_period_detail.csv"]
    )
    for filename, frame in outputs.items():
        frame.to_csv(DATA_DIR / filename, index=False, encoding="utf-8-sig")
    metadata = {
        "research_status": "研发期扩展窗口样本外；因结果将用于选模，不属于最终盲测",
        "universe": "调仓日有效的申万医药生物历史成员，包含退市及被剔除股票",
        "target": "个股未来收益-同期医药基准收益",
        "primary_healthcare_benchmark": f"{PRIMARY_HEALTHCARE_BENCHMARK} 中证申万医药生物指数",
        "benchmark_note": "801150.SI申万行业指数日行情无Tushare权限；主基准改用可直接取得的中证申万医药生物指数，ETF仅作稳健性对照",
        "market_benchmark": f"{MARKET_BENCHMARK} 沪深300",
        "etf_robustness_benchmark": f"{ETF_HEALTHCARE_BENCHMARK} 广发中证全指医药卫生ETF",
        "oos_start_year": OOS_START_YEAR,
        "horizons": list(HORIZONS),
        "ridge_alpha": RIDGE_ALPHA,
        "models": MODEL_FACTORS,
        "factor_labels": FACTOR_LABELS,
        "data_end": END_DATE,
    }
    (DATA_DIR / "return_model_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nPrimary benchmark comparison")
    print(
        outputs["return_model_summary.csv"]
        .query("healthcare_benchmark == @primary_name")
        .to_string(index=False)
    )
    print("\nBenchmark robustness")
    print(
        outputs["return_model_summary.csv"]
        .query("model == '4. 交互项+残差动量+Beta变化'")
        .to_string(index=False)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-benchmarks", action="store_true")
    arguments = parser.parse_args()
    run(arguments.refresh_benchmarks)
