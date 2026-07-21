#!/usr/bin/env python3
"""Run neutralized factor tests and expanding-window out-of-sample models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
DATA_DIR = APP_DIR / "data"
HORIZONS = (5, 20, 60, 120)
OOS_START_YEAR = 2023
RIDGE_ALPHA = 5.0
MIN_PROMOTION_REBALANCES = 20

ALPHA_FACTORS = [
    "trend_5d",
    "trend_20d",
    "trend_60_ex_20",
    "trend_120_ex_20",
    "value_bp",
    "value_ep",
    "liquidity_turnover_20d",
    "crowding_max_return_20d",
]
BASE_RISK_FACTORS = [
    "risk_volatility_20d",
    "risk_volatility_60d",
    "risk_drawdown_60d",
    "risk_max_return_20d",
]
NEW_RISK_FACTORS = [
    "risk_downside_volatility_60d",
    "risk_residual_volatility_60d",
    "risk_liquidity_pressure_60d",
    "risk_cvar_60d",
]
RISK_FACTORS = BASE_RISK_FACTORS + NEW_RISK_FACTORS
FACTOR_LABELS = {
    "trend_5d": "5日趋势",
    "trend_20d": "20日趋势",
    "trend_60_ex_20": "60日剔除近20日趋势",
    "trend_120_ex_20": "120日剔除近20日趋势",
    "value_bp": "账面市值比（BP）",
    "value_ep": "盈利收益率（EP）",
    "liquidity_turnover_20d": "20日平均换手率",
    "crowding_max_return_20d": "20日最大单日涨幅",
    "risk_volatility_20d": "20日波动率风险",
    "risk_volatility_60d": "60日波动率风险",
    "risk_drawdown_60d": "距60日高点回撤风险",
    "risk_max_return_20d": "20日最大单日涨幅风险",
    "risk_downside_volatility_60d": "60日下行波动率风险",
    "risk_residual_volatility_60d": "60日残差波动率风险",
    "risk_liquidity_pressure_60d": "60日流动性压力",
    "risk_cvar_60d": "60日尾部损失（CVaR）",
}


def robust_zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    median = values.median()
    mad = (values - median).abs().median()
    if pd.notna(mad) and mad > 0:
        scale = 1.4826 * mad
        values = values.clip(median - 3 * scale, median + 3 * scale)
    std = values.std()
    return (values - values.mean()) / std if pd.notna(std) and std > 0 else values * np.nan


def rank_ic(factor: pd.Series, target: pd.Series) -> float:
    valid = factor.notna() & target.notna()
    if valid.sum() < 30:
        return np.nan
    return factor[valid].rank(method="average").corr(target[valid].rank(method="average"))


def neutralize_alpha(frame: pd.DataFrame, factor: str) -> pd.Series:
    y = robust_zscore(frame[factor])
    size = robust_zscore(frame["log_market_cap"])
    volatility = robust_zscore(frame["risk_volatility_20d"])
    industries = pd.get_dummies(frame["healthcare_subindustry"], drop_first=True, dtype=float)
    controls = pd.concat(
        [pd.Series(1.0, index=frame.index, name="intercept"), size, volatility, industries],
        axis=1,
    )
    valid = y.notna() & controls.notna().all(axis=1)
    residual = pd.Series(np.nan, index=frame.index, dtype=float)
    if valid.sum() >= max(50, controls.shape[1] + 10):
        coefficients, *_ = np.linalg.lstsq(
            controls.loc[valid].to_numpy(float), y.loc[valid].to_numpy(float), rcond=None
        )
        residual.loc[valid] = y.loc[valid] - controls.loc[valid].to_numpy(float) @ coefficients
    return robust_zscore(residual)


def neutralize_risk(frame: pd.DataFrame, factor: str) -> pd.Series:
    """Remove industry and size while retaining idiosyncratic volatility information."""
    y = robust_zscore(frame[factor])
    size = robust_zscore(frame["log_market_cap"])
    industries = pd.get_dummies(frame["healthcare_subindustry"], drop_first=True, dtype=float)
    controls = pd.concat([pd.Series(1.0, index=frame.index, name="intercept"), size, industries], axis=1)
    valid = y.notna() & controls.notna().all(axis=1)
    residual = pd.Series(np.nan, index=frame.index, dtype=float)
    if valid.sum() >= max(50, controls.shape[1] + 10):
        coefficients, *_ = np.linalg.lstsq(
            controls.loc[valid].to_numpy(float), y.loc[valid].to_numpy(float), rcond=None
        )
        residual.loc[valid] = y.loc[valid] - controls.loc[valid].to_numpy(float) @ coefficients
    return robust_zscore(residual)


def load_panels(source_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    universe = pd.read_csv(
        source_dir / "a_share_healthcare_universe.csv",
        usecols=["ts_code", "name", "healthcare_subindustry"],
    )
    close = pd.read_csv(
        source_dir / "a_share_healthcare_prices_qfq_wide.csv", index_col=0, parse_dates=True
    ).sort_index()
    close = close.reindex(columns=universe["ts_code"]).apply(pd.to_numeric, errors="coerce")
    basic = pd.read_csv(
        source_dir / "a_share_healthcare_daily_basic_long.csv",
        usecols=["ts_code", "trade_date", "turnover_rate", "pe_ttm", "pb", "total_mv"],
        parse_dates=["trade_date"],
    )
    basic = basic[basic["ts_code"].isin(close.columns)].copy()

    panels: dict[str, pd.DataFrame] = {}
    for column in ["turnover_rate", "pe_ttm", "pb", "total_mv"]:
        panel = basic.pivot(index="trade_date", columns="ts_code", values=column)
        panels[column] = panel.reindex(index=close.index, columns=close.columns).ffill(limit=5)
    price_long = pd.read_csv(
        source_dir / "a_share_healthcare_prices_long.csv",
        usecols=["ts_code", "trade_date", "amount"],
        parse_dates=["trade_date"],
    )
    amount = price_long.pivot(index="trade_date", columns="ts_code", values="amount")
    panels["amount"] = amount.reindex(index=close.index, columns=close.columns).apply(
        pd.to_numeric, errors="coerce"
    )
    return universe, close, panels


def snapshot_features(
    position: int,
    prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
) -> pd.DataFrame:
    current = prices.iloc[position]
    frame = universe_by_code.copy()
    frame["trend_5d"] = current / prices.iloc[position - 5] - 1
    frame["trend_20d"] = current / prices.iloc[position - 20] - 1
    frame["trend_60_ex_20"] = prices.iloc[position - 20] / prices.iloc[position - 60] - 1
    frame["trend_120_ex_20"] = prices.iloc[position - 20] / prices.iloc[position - 120] - 1
    frame["log_market_cap"] = np.log(panels["total_mv"].iloc[position].where(lambda x: x > 0))
    frame["value_bp"] = 1 / panels["pb"].iloc[position].where(lambda x: x > 0)
    frame["value_ep"] = 1 / panels["pe_ttm"].iloc[position].where(lambda x: x > 0)
    frame["liquidity_turnover_20d"] = panels["turnover_rate"].iloc[position - 19 : position + 1].mean()
    trailing_returns = daily_returns.iloc[position - 59 : position + 1]
    frame["crowding_max_return_20d"] = trailing_returns.tail(20).max()
    frame["risk_volatility_20d"] = trailing_returns.tail(20).std() * np.sqrt(252)
    frame["risk_volatility_60d"] = trailing_returns.std() * np.sqrt(252)
    frame["risk_drawdown_60d"] = -(current / prices.iloc[position - 59 : position + 1].max() - 1)
    frame["risk_max_return_20d"] = frame["crowding_max_return_20d"]
    frame["risk_downside_volatility_60d"] = trailing_returns.where(trailing_returns < 0).std() * np.sqrt(252)

    market_return = trailing_returns.mean(axis=1, skipna=True)
    market_variance = market_return.var()
    beta = trailing_returns.apply(lambda series: series.cov(market_return)).div(market_variance)
    alpha = trailing_returns.mean().sub(beta * market_return.mean())
    market_component = pd.DataFrame(
        np.outer(market_return.to_numpy(), beta.to_numpy()),
        index=trailing_returns.index,
        columns=trailing_returns.columns,
    )
    residual_returns = trailing_returns.sub(market_component).sub(alpha, axis=1)
    frame["risk_residual_volatility_60d"] = residual_returns.std() * np.sqrt(252)

    trailing_amount = panels["amount"].iloc[position - 59 : position + 1]
    amount_20d = trailing_amount.tail(20).mean().where(lambda x: x > 0)
    amount_60d = trailing_amount.mean().where(lambda x: x > 0)
    liquidity_dry_up = -np.log(amount_20d / amount_60d)
    amihud = (trailing_returns.abs() / trailing_amount.where(trailing_amount > 0)).mean()
    frame["risk_liquidity_pressure_60d"] = (
        robust_zscore(liquidity_dry_up) + robust_zscore(np.log(amihud.where(amihud > 0)))
    ) / 2

    tail_count = max(1, int(np.ceil(len(trailing_returns) * 0.05)))
    frame["risk_cvar_60d"] = -trailing_returns.apply(
        lambda series: series.nsmallest(tail_count).mean() if series.notna().sum() >= 30 else np.nan
    )

    for factor in ALPHA_FACTORS:
        frame[f"raw_{factor}"] = robust_zscore(frame[factor])
        frame[factor] = neutralize_alpha(frame, factor)
    for factor in RISK_FACTORS:
        frame[f"raw_{factor}"] = robust_zscore(frame[factor])
        frame[factor] = neutralize_risk(frame, factor)
    frame.index.name = "ts_code"
    return frame


def build_horizon_panel(
    horizon: int,
    prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
) -> pd.DataFrame:
    first_position = 120
    last_position = len(prices) - horizon - 1
    positions = range(first_position, last_position + 1, horizon)
    rows = []
    for position in positions:
        features = snapshot_features(position, prices, daily_returns, panels, universe_by_code)
        entry = prices.iloc[position]
        path = prices.iloc[position + 1 : position + horizon + 1].div(entry, axis=1) - 1
        features["entry_date"] = prices.index[position]
        features["exit_date"] = prices.index[position + horizon]
        features["forward_return"] = prices.iloc[position + horizon] / entry - 1
        features["forward_drawdown_loss"] = -path.min()
        rows.append(features.reset_index())
    return pd.concat(rows, ignore_index=True)


def assign_deciles(series: pd.Series) -> pd.Series:
    valid = series.notna()
    result = pd.Series(pd.NA, index=series.index, dtype="Int64")
    if valid.sum() >= 50:
        result.loc[valid] = pd.qcut(series[valid].rank(method="first"), 10, labels=False) + 1
    return result


def single_factor_tests(panel: pd.DataFrame, horizon: int) -> tuple[list[dict], list[dict]]:
    summary_rows: list[dict] = []
    decile_rows: list[dict] = []
    definitions = [
        (factor, "收益", "forward_return") for factor in ALPHA_FACTORS
    ] + [(factor, "回撤风险", "forward_drawdown_loss") for factor in RISK_FACTORS]
    for factor, target_label, target in definitions:
        for version, column in [("原始", f"raw_{factor}"), ("中性化", factor)]:
            period_ics = panel.groupby("entry_date", sort=True).apply(
                lambda frame: rank_ic(frame[column], frame[target]), include_groups=False
            ).dropna()
            decile_data = panel[["entry_date", column, target]].dropna().copy()
            decile_data["decile"] = decile_data.groupby("entry_date")[column].transform(assign_deciles)
            decile_means = decile_data.groupby(["entry_date", "decile"], as_index=False)[target].mean()
            average_deciles = decile_means.groupby("decile")[target].mean()
            summary_rows.append(
                {
                    "horizon_sessions": horizon,
                    "factor": factor,
                    "factor_label": FACTOR_LABELS[factor],
                    "factor_type": "收益因子" if target_label == "收益" else "风险因子",
                    "target": target_label,
                    "version": version,
                    "mean_rank_ic": period_ics.mean(),
                    "rank_ic_ir": period_ics.mean() / period_ics.std() if period_ics.std() > 0 else np.nan,
                    "positive_ic_rate": (period_ics > 0).mean(),
                    "top_bottom_spread": average_deciles.get(10, np.nan) - average_deciles.get(1, np.nan),
                    "period_count": int(period_ics.count()),
                }
            )
            for decile, value in average_deciles.items():
                decile_rows.append(
                    {
                        "horizon_sessions": horizon,
                        "factor": factor,
                        "factor_label": FACTOR_LABELS[factor],
                        "target": target_label,
                        "version": version,
                        "decile": int(decile),
                        "average_target": value,
                    }
                )
    return summary_rows, decile_rows


def fit_ridge(frame: pd.DataFrame, factors: list[str], target: str) -> tuple[np.ndarray, np.ndarray]:
    x = frame[factors].fillna(0).to_numpy(float)
    y = frame[target].to_numpy(float)
    valid = np.isfinite(y)
    x = x[valid]
    y = y[valid]
    y = y - frame.loc[valid].groupby("entry_date")[target].transform("mean").to_numpy(float)
    x_design = np.column_stack([np.ones(len(x)), x])
    penalty = np.eye(x_design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(x_design.T @ x_design + penalty, x_design.T @ y)
    return coefficients[0], coefficients[1:]


def predict(frame: pd.DataFrame, factors: list[str], intercept: float, coefficients: np.ndarray) -> pd.Series:
    return pd.Series(intercept + frame[factors].fillna(0).to_numpy(float) @ coefficients, index=frame.index)


def score_percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True) * 100


def model_metrics(
    test: pd.DataFrame,
    prediction_column: str,
    target: str,
    horizon: int,
    year: int,
    model: str,
) -> dict:
    period_ics = test.groupby("entry_date", sort=True).apply(
        lambda frame: rank_ic(frame[prediction_column], frame[target]), include_groups=False
    ).dropna()
    ranked = test[["entry_date", prediction_column, target]].dropna().copy()
    ranked["decile"] = ranked.groupby("entry_date")[prediction_column].transform(assign_deciles)
    top = ranked[ranked["decile"] == 10].groupby("entry_date")[target].mean()
    bottom = ranked[ranked["decile"] == 1].groupby("entry_date")[target].mean()
    return {
        "horizon_sessions": horizon,
        "test_year": year,
        "model": model,
        "target": "未来收益" if target == "forward_return" else "未来最大回撤风险",
        "mean_rank_ic": period_ics.mean(),
        "rank_ic_ir": period_ics.mean() / period_ics.std() if period_ics.std() > 0 else np.nan,
        "positive_ic_rate": (period_ics > 0).mean(),
        "top_decile_target": top.mean(),
        "bottom_decile_target": bottom.mean(),
        "top_bottom_spread": (top - bottom).mean(),
        "rebalance_count": int(test["entry_date"].nunique()),
        "observation_count": int(len(test)),
    }


def out_of_sample_models(panel: pd.DataFrame, horizon: int) -> tuple[list[dict], list[dict]]:
    metrics_rows: list[dict] = []
    coefficient_rows: list[dict] = []
    for year in range(OOS_START_YEAR, panel["entry_date"].dt.year.max() + 1):
        cutoff = pd.Timestamp(f"{year}-01-01")
        train = panel[panel["exit_date"] < cutoff].copy()
        test = panel[panel["entry_date"].dt.year == year].copy()
        if len(train) < 500 or test.empty:
            continue
        for model, factors, target, pred_col in [
            ("收益模型", ALPHA_FACTORS, "forward_return", "predicted_return"),
            ("基础回撤模型", BASE_RISK_FACTORS, "forward_drawdown_loss", "predicted_base_risk"),
            ("增强回撤模型", RISK_FACTORS, "forward_drawdown_loss", "predicted_enhanced_risk"),
        ]:
            intercept, coefficients = fit_ridge(train, factors, target)
            test[pred_col] = predict(test, factors, intercept, coefficients)
            metrics_rows.append(model_metrics(test, pred_col, target, horizon, year, model))
            for factor, coefficient in zip(factors, coefficients):
                coefficient_rows.append(
                    {
                        "horizon_sessions": horizon,
                        "test_year": year,
                        "model": model,
                        "factor": factor,
                        "factor_label": FACTOR_LABELS[factor],
                        "coefficient": coefficient,
                    }
                )
    return metrics_rows, coefficient_rows


def current_scores(
    panels_by_horizon: dict[int, pd.DataFrame],
    prices: pd.DataFrame,
    daily_returns: pd.DataFrame,
    basic_panels: dict[str, pd.DataFrame],
    universe_by_code: pd.DataFrame,
    model_selection: pd.DataFrame,
) -> pd.DataFrame:
    current = snapshot_features(len(prices) - 1, prices, daily_returns, basic_panels, universe_by_code)
    rows = []
    for horizon, panel in panels_by_horizon.items():
        available = panel[panel["exit_date"] <= prices.index[-1]].copy()
        return_intercept, return_coef = fit_ridge(available, ALPHA_FACTORS, "forward_return")
        selected_model = model_selection.loc[
            model_selection["horizon_sessions"] == horizon, "selected_model"
        ].iloc[0]
        selected_factors = RISK_FACTORS if selected_model == "增强回撤模型" else BASE_RISK_FACTORS
        risk_intercept, risk_coef = fit_ridge(available, selected_factors, "forward_drawdown_loss")
        result = current[["name", "healthcare_subindustry"]].copy()
        result["horizon_sessions"] = horizon
        result["expected_return_score"] = score_percentile(
            predict(current, ALPHA_FACTORS, return_intercept, return_coef)
        )
        result["drawdown_risk_score"] = score_percentile(
            predict(current, selected_factors, risk_intercept, risk_coef)
        )
        result["risk_model_version"] = selected_model
        result["model_training_end"] = available["exit_date"].max()
        result.index.name = "ts_code"
        rows.append(result.reset_index())
    return pd.concat(rows, ignore_index=True)


def select_risk_models(oos_yearly: pd.DataFrame, oos_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in HORIZONS:
        summary = oos_summary[oos_summary["horizon_sessions"] == horizon].set_index("model")
        base = summary.loc["基础回撤模型"]
        enhanced = summary.loc["增强回撤模型"]
        yearly = oos_yearly[
            (oos_yearly["horizon_sessions"] == horizon)
            & oos_yearly["model"].isin(["基础回撤模型", "增强回撤模型"])
        ].pivot(index="test_year", columns="model", values="mean_rank_ic")
        improved_year_rate = (yearly["增强回撤模型"] > yearly["基础回撤模型"]).mean()
        ic_improved = enhanced["mean_rank_ic"] > base["mean_rank_ic"]
        spread_improved = enhanced["top_bottom_spread"] > base["top_bottom_spread"]
        stability_passed = improved_year_rate >= 0.5
        sample_passed = base["rebalance_count"] >= MIN_PROMOTION_REBALANCES
        selected = (
            "增强回撤模型"
            if ic_improved and spread_improved and stability_passed and sample_passed
            else "基础回撤模型"
        )
        rows.append(
            {
                "horizon_sessions": horizon,
                "selected_model": selected,
                "base_mean_rank_ic": base["mean_rank_ic"],
                "enhanced_mean_rank_ic": enhanced["mean_rank_ic"],
                "rank_ic_change": enhanced["mean_rank_ic"] - base["mean_rank_ic"],
                "base_top_bottom_spread": base["top_bottom_spread"],
                "enhanced_top_bottom_spread": enhanced["top_bottom_spread"],
                "spread_change": enhanced["top_bottom_spread"] - base["top_bottom_spread"],
                "improved_year_rate": improved_year_rate,
                "sample_passed": sample_passed,
                "promotion_passed": selected == "增强回撤模型",
            }
        )
    return pd.DataFrame(rows)


def aggregate_oos(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (horizon, model, target), frame in metrics.groupby(["horizon_sessions", "model", "target"]):
        weights = frame["rebalance_count"]
        rows.append(
            {
                "horizon_sessions": horizon,
                "model": model,
                "target": target,
                "mean_rank_ic": np.average(frame["mean_rank_ic"], weights=weights),
                "rank_ic_ir": frame["mean_rank_ic"].mean() / frame["mean_rank_ic"].std()
                if frame["mean_rank_ic"].std() > 0 else np.nan,
                "positive_year_rate": (frame["mean_rank_ic"] > 0).mean(),
                "top_decile_target": np.average(frame["top_decile_target"], weights=weights),
                "bottom_decile_target": np.average(frame["bottom_decile_target"], weights=weights),
                "top_bottom_spread": np.average(frame["top_bottom_spread"], weights=weights),
                "test_year_count": frame["test_year"].nunique(),
                "rebalance_count": frame["rebalance_count"].sum(),
                "observation_count": frame["observation_count"].sum(),
            }
        )
    return pd.DataFrame(rows)


def run_research(source_dir: Path) -> None:
    universe, close, basic_panels = load_panels(source_dir)
    prices = close.ffill(limit=3)
    daily_returns = prices.pct_change(fill_method=None)
    universe_by_code = universe.set_index("ts_code")
    factor_rows: list[dict] = []
    decile_rows: list[dict] = []
    oos_rows: list[dict] = []
    coefficient_rows: list[dict] = []
    panels_by_horizon: dict[int, pd.DataFrame] = {}
    for horizon in HORIZONS:
        panel = build_horizon_panel(horizon, prices, daily_returns, basic_panels, universe_by_code)
        panels_by_horizon[horizon] = panel
        factor_result, decile_result = single_factor_tests(panel, horizon)
        oos_result, coefficient_result = out_of_sample_models(panel, horizon)
        factor_rows.extend(factor_result)
        decile_rows.extend(decile_result)
        oos_rows.extend(oos_result)
        coefficient_rows.extend(coefficient_result)

    factor_summary = pd.DataFrame(factor_rows)
    deciles = pd.DataFrame(decile_rows)
    oos_yearly = pd.DataFrame(oos_rows)
    coefficients = pd.DataFrame(coefficient_rows)
    oos_summary = aggregate_oos(oos_yearly)
    model_selection = select_risk_models(oos_yearly, oos_summary)
    scores = current_scores(
        panels_by_horizon, prices, daily_returns, basic_panels, universe_by_code, model_selection
    )
    metadata = {
        "data_start": close.index.min().strftime("%Y-%m-%d"),
        "data_end": close.index.max().strftime("%Y-%m-%d"),
        "oos_start_year": OOS_START_YEAR,
        "horizons": list(HORIZONS),
        "ridge_alpha": RIDGE_ALPHA,
        "alpha_neutralization": "子行业哑变量 + 对数总市值 + 20日波动率",
        "risk_neutralization": "子行业哑变量 + 对数总市值；保留个股波动率作为风险信息",
        "base_risk_factors": [FACTOR_LABELS[factor] for factor in BASE_RISK_FACTORS],
        "new_risk_factors": [FACTOR_LABELS[factor] for factor in NEW_RISK_FACTORS],
        "risk_model_promotion_rule": "平均样本外Rank IC提高、十分位回撤差扩大、至少半数测试年度IC改善、且不少于20个独立调仓期",
        "risk_model_min_promotion_rebalances": MIN_PROMOTION_REBALANCES,
        "universe_note": "使用当前310只股票的历史数据，存在幸存者偏差。",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "factor_research_summary.csv": factor_summary,
        "factor_decile_returns.csv": deciles,
        "model_oos_yearly.csv": oos_yearly,
        "model_oos_summary.csv": oos_summary,
        "model_coefficients.csv": coefficients,
        "model_current_scores.csv": scores,
        "risk_model_selection.csv": model_selection,
    }
    for filename, frame in outputs.items():
        frame.to_csv(DATA_DIR / filename, index=False, encoding="utf-8-sig")
    (DATA_DIR / "factor_research_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(oos_summary.to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    run_research(args.source_dir.resolve())
