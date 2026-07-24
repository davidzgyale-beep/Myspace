#!/usr/bin/env python3
"""Backtest the 7-factor 20-day MAE model on a point-in-time SW healthcare universe."""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from factor_research import (
    DATA_DIR,
    OOS_START_YEAR,
    PRODUCTION_RISK_FACTORS,
    apply_production_risk_neutralization,
    fit_ridge,
    load_panels,
    maximum_adverse_excursion,
    model_metrics,
    predict,
    rank_ic,
    robust_zscore,
    score_percentile,
    snapshot_features,
)


APP_DIR = Path(__file__).resolve().parent
SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
CACHE_DIR = DATA_DIR / "survivorship_free_cache"
PRICE_CACHE_DIR = CACHE_DIR / "prices"
BASIC_CACHE_DIR = CACHE_DIR / "daily_basic"
START_DATE = "20190101"
END_DATE = "20260720"
SW_HEALTHCARE_L1 = "801150.SI"
HORIZON = 20
SEVEN_FACTORS = PRODUCTION_RISK_FACTORS
SLEEP_SECONDS = 0.12

PRICE_FIELDS = (
    "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
)
BASIC_FIELDS = "ts_code,trade_date,turnover_rate,pe_ttm,pb,total_mv"
MEMBER_FIELDS = "index_code,index_name,con_code,con_name,in_date,out_date,is_new"


def load_tushare_query():
    path = SOURCE_DIR / "build_a_share_healthcare_universe.py"
    spec = importlib.util.spec_from_file_location("healthcare_universe_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.tushare_query


def fetch_memberships(query, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    l1_path = CACHE_DIR / "sw_healthcare_l1_membership.csv"
    l2_path = CACHE_DIR / "sw_healthcare_l2_membership.csv"
    if refresh or not l1_path.exists():
        l1 = query(
            "index_member", index_code=SW_HEALTHCARE_L1, fields=MEMBER_FIELDS
        )
        l1.to_csv(l1_path, index=False, encoding="utf-8-sig")
    else:
        l1 = pd.read_csv(l1_path)
    if refresh or not l2_path.exists():
        classes = query(
            "index_classify",
            src="SW2021",
            level="L2",
            fields="index_code,industry_name,level,industry_code,parent_code,src",
        )
        classes = classes[classes["industry_code"].astype(str).str.startswith("37")]
        frames = []
        for _, industry in classes.iterrows():
            members = query(
                "index_member", index_code=industry["index_code"], fields=MEMBER_FIELDS
            )
            members["subindustry"] = industry["industry_name"]
            frames.append(members)
            time.sleep(SLEEP_SECONDS)
        l2 = pd.concat(frames, ignore_index=True)
        l2.to_csv(l2_path, index=False, encoding="utf-8-sig")
    else:
        l2 = pd.read_csv(l2_path)
    for frame in (l1, l2):
        frame["in_date"] = pd.to_datetime(frame["in_date"], format="%Y%m%d", errors="coerce")
        frame["out_date"] = pd.to_datetime(frame["out_date"], format="%Y%m%d", errors="coerce")
    return l1, l2


def relevant_memberships(frame: pd.DataFrame) -> pd.DataFrame:
    start = pd.Timestamp(START_DATE)
    end = pd.Timestamp(END_DATE)
    return frame[
        frame["in_date"].le(end)
        & (frame["out_date"].isna() | frame["out_date"].ge(start))
    ].copy()


def fetch_one_price(query, code: str) -> pd.DataFrame:
    daily = query(
        "daily",
        ts_code=code,
        start_date=START_DATE,
        end_date=END_DATE,
        fields=PRICE_FIELDS,
    )
    time.sleep(SLEEP_SECONDS)
    adj = query(
        "adj_factor",
        ts_code=code,
        start_date=START_DATE,
        end_date=END_DATE,
        fields="ts_code,trade_date,adj_factor",
    )
    if daily.empty or adj.empty:
        return pd.DataFrame()
    frame = daily.merge(adj, on=["ts_code", "trade_date"], how="inner")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    numeric = [column for column in frame if column not in {"ts_code", "trade_date"}]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    latest_adjustment = frame["adj_factor"].dropna().iloc[-1]
    for column in ["open", "high", "low", "close"]:
        frame[f"{column}_qfq"] = frame[column] * frame["adj_factor"] / latest_adjustment
    return frame.sort_values("trade_date")


def fetch_one_basic(query, code: str) -> pd.DataFrame:
    frame = query(
        "daily_basic",
        ts_code=code,
        start_date=START_DATE,
        end_date=END_DATE,
        fields=BASIC_FIELDS,
    )
    if frame.empty:
        return frame
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
    numeric = [column for column in frame if column not in {"ts_code", "trade_date"}]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    return frame.sort_values("trade_date")


def local_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = pd.read_csv(SOURCE_DIR / "a_share_healthcare_prices_long.csv", parse_dates=["trade_date"])
    basic = pd.read_csv(SOURCE_DIR / "a_share_healthcare_daily_basic_long.csv", parse_dates=["trade_date"])
    return prices, basic


def fetch_missing_history(
    query, codes: list[str], local_codes: set[str]
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BASIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    for number, code in enumerate(codes, 1):
        if code in local_codes:
            continue
        price_path = PRICE_CACHE_DIR / f"{code}.csv"
        basic_path = BASIC_CACHE_DIR / f"{code}.csv"
        try:
            if not price_path.exists():
                price = fetch_one_price(query, code)
                if price.empty:
                    failures.append({"ts_code": code, "dataset": "price", "message": "empty"})
                else:
                    price.to_csv(price_path, index=False, encoding="utf-8-sig")
                time.sleep(SLEEP_SECONDS)
            if not basic_path.exists():
                basic = fetch_one_basic(query, code)
                if basic.empty:
                    failures.append({"ts_code": code, "dataset": "daily_basic", "message": "empty"})
                else:
                    basic.to_csv(basic_path, index=False, encoding="utf-8-sig")
                time.sleep(SLEEP_SECONDS)
            print(f"[{number}/{len(codes)}] {code} cached", flush=True)
        except Exception as error:
            failures.append({"ts_code": code, "dataset": "request", "message": str(error)})
            print(f"[{number}/{len(codes)}] {code} failed: {error}", flush=True)
    price_frames = [pd.read_csv(path, parse_dates=["trade_date"]) for path in PRICE_CACHE_DIR.glob("*.csv")]
    basic_frames = [pd.read_csv(path, parse_dates=["trade_date"]) for path in BASIC_CACHE_DIR.glob("*.csv")]
    return (
        pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame(),
        pd.concat(basic_frames, ignore_index=True) if basic_frames else pd.DataFrame(),
        failures,
    )


def active_mask(
    dates: pd.DatetimeIndex, codes: list[str], membership: pd.DataFrame
) -> pd.DataFrame:
    result = pd.DataFrame(False, index=dates, columns=codes)
    for row in membership.itertuples():
        end = row.out_date if pd.notna(row.out_date) else dates.max()
        if row.con_code in result.columns:
            result.loc[(dates >= row.in_date) & (dates <= end), row.con_code] = True
    return result


def subindustry_at_date(
    date: pd.Timestamp, codes: pd.Index, membership: pd.DataFrame
) -> pd.Series:
    active = membership[
        membership["in_date"].le(date)
        & (membership["out_date"].isna() | membership["out_date"].ge(date))
        & membership["con_code"].isin(codes)
    ]
    mapping = active.drop_duplicates("con_code", keep="last").set_index("con_code")["subindustry"]
    return pd.Series(codes, index=codes).map(mapping).fillna("医药生物-未细分")


def neutralize(frame: pd.DataFrame, factor: str) -> pd.Series:
    y = robust_zscore(frame[factor])
    size = robust_zscore(frame["log_market_cap"])
    industries = pd.get_dummies(frame["subindustry"], drop_first=True, dtype=float)
    controls = pd.concat(
        [pd.Series(1.0, index=frame.index, name="intercept"), size, industries], axis=1
    )
    valid = y.notna() & controls.notna().all(axis=1)
    residual = pd.Series(np.nan, index=frame.index, dtype=float)
    if valid.sum() >= max(50, controls.shape[1] + 10):
        coefficients, *_ = np.linalg.lstsq(
            controls.loc[valid].to_numpy(float), y.loc[valid].to_numpy(float), rcond=None
        )
        residual.loc[valid] = y.loc[valid] - controls.loc[valid].to_numpy(float) @ coefficients
    return robust_zscore(residual)


def add_diagnostics(metrics: dict, frame: pd.DataFrame, prediction_column: str) -> dict:
    scored = frame[["entry_date", "forward_drawdown_loss", prediction_column]].dropna().copy()
    target = "forward_drawdown_loss"
    scored["target_centered"] = scored[target] - scored.groupby("entry_date")[target].transform("mean")
    error = scored[prediction_column] - scored["target_centered"]
    scored["predicted_decile"] = scored.groupby("entry_date")[prediction_column].transform(
        lambda values: pd.qcut(values.rank(method="first"), 10, labels=False) + 1
    )
    scored["actual_decile"] = scored.groupby("entry_date")[target].transform(
        lambda values: pd.qcut(values.rank(method="first"), 10, labels=False) + 1
    )
    actual_tail = scored["actual_decile"] == 10
    metrics["demeaned_rmse"] = float(np.sqrt(np.mean(np.square(error))))
    metrics["demeaned_mae"] = float(np.mean(np.abs(error)))
    metrics["top_decile_recall"] = float(
        ((scored["predicted_decile"] == 10) & actual_tail).sum() / actual_tail.sum()
    )
    return metrics


def build_panel(
    prices_long: pd.DataFrame,
    basic_long: pd.DataFrame,
    l1: pd.DataFrame,
    l2: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    codes = sorted(l1["con_code"].unique())
    prices_long = prices_long[prices_long["ts_code"].isin(codes)].copy()
    basic_long = basic_long[basic_long["ts_code"].isin(codes)].copy()
    panels = {}
    for column in ["open_qfq", "high_qfq", "low_qfq", "close_qfq", "amount"]:
        panels[column] = prices_long.pivot(index="trade_date", columns="ts_code", values=column).sort_index()
    dates = panels["close_qfq"].index
    for column in panels:
        panels[column] = panels[column].reindex(index=dates, columns=codes)
    for column in ["turnover_rate", "total_mv"]:
        panels[column] = (
            basic_long.pivot(index="trade_date", columns="ts_code", values=column)
            .reindex(index=dates, columns=codes)
            .ffill(limit=5)
        )
    membership_mask = active_mask(dates, codes, l1)
    # Forward filling after the last trade treats delisting proceeds as cash at the last tradable price.
    close = panels["close_qfq"].ffill()
    returns = close.pct_change(fill_method=None)
    sector_returns = returns.where(membership_mask).mean(axis=1, skipna=True)
    positions = range(120, len(dates) - HORIZON, HORIZON)
    rows = []
    universe_rows = []
    for position in positions:
        entry_date = dates[position]
        eligible = membership_mask.iloc[position]
        entry_codes = eligible[eligible].index
        entry = close.iloc[position].reindex(entry_codes)
        trailing_returns = returns.iloc[position - 59 : position + 1].reindex(columns=entry_codes)
        frame = pd.DataFrame(index=entry_codes)
        frame["subindustry"] = subindustry_at_date(entry_date, entry_codes, l2)
        frame["log_market_cap"] = np.log(
            panels["total_mv"].iloc[position].reindex(entry_codes).where(lambda values: values > 0)
        )
        frame["risk_volatility_60d"] = trailing_returns.std() * np.sqrt(252)
        frame["risk_downside_volatility_60d"] = (
            trailing_returns.where(trailing_returns < 0).std() * np.sqrt(252)
        )
        frame["risk_max_return_20d"] = trailing_returns.tail(20).max()
        trailing_sector = sector_returns.iloc[position - 59 : position + 1]
        frame["risk_healthcare_beta_60d"] = trailing_returns.apply(
            lambda series: series.cov(trailing_sector)
        ).div(trailing_sector.var())
        trailing_open = panels["open_qfq"].iloc[position - 59 : position + 1].reindex(columns=entry_codes)
        trailing_high = panels["high_qfq"].iloc[position - 59 : position + 1].reindex(columns=entry_codes)
        trailing_low = panels["low_qfq"].iloc[position - 59 : position + 1].reindex(columns=entry_codes)
        trailing_close = close.iloc[position - 59 : position + 1].reindex(columns=entry_codes)
        previous_close = trailing_close.shift(1)
        gap_down = (trailing_open / previous_close - 1).where(lambda values: values < 0)
        extreme_down = trailing_returns.where(trailing_returns < 0)
        frame["risk_gap_extreme_down_60d"] = (
            -gap_down.min().fillna(0)
            + -extreme_down.min().fillna(0)
            + (trailing_returns <= -0.095).sum().mul(0.05)
        )
        quarter_turnover = panels["turnover_rate"].iloc[position - 119 : position + 1].reindex(columns=entry_codes)
        quarter_amount = panels["amount"].iloc[position - 119 : position + 1].reindex(columns=entry_codes)
        turnover_change = np.log(
            quarter_turnover.tail(20).mean().where(lambda values: values > 0)
            / quarter_turnover.head(60).mean().where(lambda values: values > 0)
        )
        amount_change = np.log(
            quarter_amount.tail(20).mean().where(lambda values: values > 0)
            / quarter_amount.head(60).mean().where(lambda values: values > 0)
        )
        frame["risk_crowding_quarter_change"] = (
            robust_zscore(turnover_change) + robust_zscore(amount_change)
        ) / 2
        true_range = pd.DataFrame(
            np.maximum.reduce(
                [
                    (trailing_high - trailing_low).to_numpy(),
                    (trailing_high - previous_close).abs().to_numpy(),
                    (trailing_low - previous_close).abs().to_numpy(),
                ]
            ),
            index=trailing_high.index,
            columns=entry_codes,
        )
        frame["risk_intraday_atr_20d"] = true_range.tail(20).mean().div(
            trailing_close.tail(20).mean()
        )
        for factor in SEVEN_FACTORS:
            frame[factor] = neutralize(frame, factor)
        future_path = close.iloc[position + 1 : position + HORIZON + 1].reindex(
            columns=entry_codes
        ).div(entry, axis=1) - 1
        frame["forward_drawdown_loss"] = maximum_adverse_excursion(future_path)
        frame["entry_date"] = entry_date
        frame["exit_date"] = dates[position + HORIZON]
        frame.index.name = "ts_code"
        rows.append(frame.reset_index())
        universe_rows.append(
            {
                "entry_date": entry_date,
                "eligible_count": len(entry_codes),
                "usable_target_count": int(frame["forward_drawdown_loss"].notna().sum()),
            }
        )
    return pd.concat(rows, ignore_index=True), pd.DataFrame(universe_rows)


def evaluate(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    yearly_rows = []
    period_rows = []
    for year in range(OOS_START_YEAR, panel["entry_date"].dt.year.max() + 1):
        cutoff = pd.Timestamp(f"{year}-01-01")
        train = panel[panel["exit_date"] < cutoff]
        test = panel[panel["entry_date"].dt.year == year].copy()
        intercept, coefficients = fit_ridge(train, SEVEN_FACTORS, "forward_drawdown_loss")
        test["predicted_mae"] = predict(test, SEVEN_FACTORS, intercept, coefficients)
        metrics = model_metrics(
            test,
            "predicted_mae",
            "forward_drawdown_loss",
            HORIZON,
            year,
            "动态申万医疗7因子-Ridge",
        )
        yearly_rows.append(add_diagnostics(metrics, test, "predicted_mae"))
        ics = test.groupby("entry_date", sort=True).apply(
            lambda group: rank_ic(group["predicted_mae"], group["forward_drawdown_loss"]),
            include_groups=False,
        ).dropna()
        period_rows.extend(
            {"entry_date": date, "test_year": year, "rank_ic": value}
            for date, value in ics.items()
        )
    yearly = pd.DataFrame(yearly_rows)
    periods = pd.DataFrame(period_rows)
    weights = yearly["rebalance_count"]
    summary = pd.DataFrame(
        [
            {
                "horizon_sessions": HORIZON,
                "model": "动态申万医疗7因子-Ridge",
                "mean_rank_ic": np.average(yearly["mean_rank_ic"], weights=weights),
                "top_bottom_spread": np.average(yearly["top_bottom_spread"], weights=weights),
                "top_decile_recall": np.average(yearly["top_decile_recall"], weights=weights),
                "rebalance_count": int(yearly["rebalance_count"].sum()),
                "observation_count": int(yearly["observation_count"].sum()),
            }
        ]
    )
    return summary, yearly, periods


def export_production_model(
    panel: pd.DataFrame,
    l1: pd.DataFrame,
    l2: pd.DataFrame,
    all_prices_long: pd.DataFrame,
) -> None:
    """Fit the frozen 20-day model and score the dashboard's current 310-stock display set."""
    production_train = panel[panel["exit_date"] <= pd.Timestamp(END_DATE)].copy()
    intercept, coefficients = fit_ridge(
        production_train, SEVEN_FACTORS, "forward_drawdown_loss"
    )
    coefficient_frame = pd.DataFrame(
        {
            "factor": SEVEN_FACTORS,
            "factor_label": [
                {
                    "risk_intraday_atr_20d": "20日日内振幅/ATR",
                    "risk_volatility_60d": "60日波动率",
                    "risk_downside_volatility_60d": "60日下行波动率",
                    "risk_max_return_20d": "20日最大单日涨幅",
                    "risk_gap_extreme_down_60d": "跳空与极端下跌",
                    "risk_healthcare_beta_60d": "60日医疗板块Beta",
                    "risk_crowding_quarter_change": "拥挤度季度变化",
                }[factor]
                for factor in SEVEN_FACTORS
            ],
            "coefficient": coefficients,
        }
    )
    coefficient_frame.to_csv(
        DATA_DIR / "production_risk_model_coefficients.csv",
        index=False,
        encoding="utf-8-sig",
    )

    universe, close, panels, benchmark_close = load_panels(SOURCE_DIR)
    full_universe = pd.read_csv(
        SOURCE_DIR / "a_share_healthcare_universe.csv",
        usecols=["ts_code", "in_sw_healthcare"],
    )
    prices = close.ffill(limit=3)
    current = snapshot_features(
        len(prices) - 1,
        prices,
        prices.pct_change(fill_method=None),
        benchmark_close.pct_change(fill_method=None),
        panels,
        universe.set_index("ts_code"),
    )
    current_date = prices.index[-1]
    current_sw_codes = l1.loc[
        l1["in_date"].le(current_date)
        & (l1["out_date"].isna() | l1["out_date"].ge(current_date)),
        "con_code",
    ].unique()
    all_close = (
        all_prices_long.pivot(index="trade_date", columns="ts_code", values="close_qfq")
        .sort_index()
        .ffill(limit=3)
    )
    trailing_returns = all_close.pct_change(fill_method=None).iloc[-60:]
    active_sw_codes = [code for code in current_sw_codes if code in trailing_returns]
    dynamic_healthcare_return = trailing_returns[active_sw_codes].mean(axis=1, skipna=True)
    current_beta = trailing_returns.reindex(columns=current.index).apply(
        lambda series: series.cov(dynamic_healthcare_return)
    ).div(dynamic_healthcare_return.var())
    current["raw_risk_healthcare_beta_60d"] = robust_zscore(current_beta)
    current_l2 = subindustry_at_date(current_date, current.index, l2).to_dict()
    theme_only_codes = full_universe.loc[
        ~full_universe["in_sw_healthcare"], "ts_code"
    ]
    current_l2.update({code: "非申万医疗主题" for code in theme_only_codes})
    deployment = {
        "model_version": "动态申万历史7因子-Ridge",
        "horizon_sessions": HORIZON,
        "intercept": float(intercept),
        "coefficients": {
            factor: float(coefficient)
            for factor, coefficient in zip(SEVEN_FACTORS, coefficients)
        },
        "training_end": production_train["exit_date"].max().strftime("%Y-%m-%d"),
        "training_start": production_train["entry_date"].min().strftime("%Y-%m-%d"),
        "training_observations": int(len(production_train)),
        "training_rebalance_dates": int(production_train["entry_date"].nunique()),
        "training_universe": "调仓日有效的申万医药生物一级行业历史成员",
        "scoring_universe": "当前看板310只广义医疗股票",
        "scoring_neutralization": "当前有效申万二级行业 + 对数总市值",
        "healthcare_beta_benchmark": "当前有效申万医药生物一级行业成员等权日收益",
        "healthcare_beta_benchmark_stock_count": len(active_sw_codes),
        "scoring_subindustry_by_code": current_l2,
        "theme_only_extrapolation_count": int((~full_universe["in_sw_healthcare"]).sum()),
        "ridge_alpha": 5.0,
    }
    production_current = apply_production_risk_neutralization(current, deployment)
    risk_score = score_percentile(
        predict(production_current, SEVEN_FACTORS, intercept, coefficients)
    )
    score_path = DATA_DIR / "model_current_scores.csv"
    scores = pd.read_csv(score_path)
    is_twenty_day = scores["horizon_sessions"].eq(HORIZON)
    replacement = current[["name", "healthcare_subindustry"]].copy()
    replacement["horizon_sessions"] = HORIZON
    old_expected_return = scores.loc[
        is_twenty_day, ["ts_code", "expected_return_score"]
    ].set_index("ts_code")["expected_return_score"]
    replacement["expected_return_score"] = old_expected_return.reindex(replacement.index)
    replacement["drawdown_risk_score"] = risk_score
    replacement["risk_model_version"] = "动态申万历史7因子-Ridge"
    replacement["model_training_end"] = production_train["exit_date"].max()
    replacement.index.name = "ts_code"
    scores = pd.concat(
        [scores.loc[~is_twenty_day], replacement.reset_index()],
        ignore_index=True,
    ).sort_values(["horizon_sessions", "ts_code"])
    scores["model_training_end"] = pd.to_datetime(
        scores["model_training_end"], format="mixed"
    ).dt.strftime("%Y-%m-%d")
    scores.to_csv(score_path, index=False, encoding="utf-8-sig")

    (DATA_DIR / "production_risk_model.json").write_text(
        json.dumps(deployment, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run(refresh_membership: bool) -> None:
    query = load_tushare_query()
    l1, l2 = fetch_memberships(query, refresh_membership)
    l1 = relevant_memberships(l1)
    l2 = relevant_memberships(l2)
    codes = sorted(l1["con_code"].unique())
    local_prices, local_basic = local_frames()
    local_codes = set(local_prices["ts_code"].unique())
    fetched_prices, fetched_basic, failures = fetch_missing_history(query, codes, local_codes)
    prices = pd.concat([local_prices, fetched_prices], ignore_index=True, sort=False)
    basic = pd.concat([local_basic, fetched_basic], ignore_index=True, sort=False)
    prices = prices.drop_duplicates(["ts_code", "trade_date"], keep="last")
    basic = basic.drop_duplicates(["ts_code", "trade_date"], keep="last")
    panel, universe_counts = build_panel(prices, basic, l1, l2)
    panel[
        [
            "ts_code",
            "entry_date",
            "exit_date",
            "forward_drawdown_loss",
            *SEVEN_FACTORS,
        ]
    ].to_csv(
        DATA_DIR / "survivorship_free_training_panel.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8",
    )
    summary, yearly, periods = evaluate(panel)
    export_production_model(panel, l1, l2, prices)
    outputs = {
        "survivorship_free_risk_model_summary.csv": summary,
        "survivorship_free_risk_model_yearly.csv": yearly,
        "survivorship_free_risk_model_period_ic.csv": periods,
        "survivorship_free_universe_counts.csv": universe_counts,
        "survivorship_free_fetch_failures.csv": pd.DataFrame(failures),
    }
    for filename, frame in outputs.items():
        frame.to_csv(DATA_DIR / filename, index=False, encoding="utf-8-sig")
    metadata = {
        "universe_definition": "调仓日有效的申万医药生物一级行业历史成员",
        "membership_rule": "in_date <= 调仓日 <= out_date；out_date为空则持续有效",
        "membership_unique_codes_2019_2026": len(codes),
        "target": "max(0, -min(未来20日相对入场价收益路径))",
        "delisting_treatment": "退市或停止交易后按最后可交易前复权价格持有现金至20日结束",
        "oos_start_year": OOS_START_YEAR,
        "research_period_contaminated": True,
        "production_model_unchanged": True,
    }
    (DATA_DIR / "survivorship_free_risk_model_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nSummary")
    print(summary.to_string(index=False))
    print("\nYearly")
    print(yearly.to_string(index=False))
    print("\nUniverse counts")
    print(universe_counts.describe().to_string())
    print(f"\nFailures: {len(failures)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-membership", action="store_true")
    parser.add_argument(
        "--end-date",
        help="YYYYMMDD; defaults to the latest date in the source price panel",
    )
    args = parser.parse_args()
    if args.end_date:
        pd.to_datetime(args.end_date, format="%Y%m%d", errors="raise")
        END_DATE = args.end_date
    else:
        source_dates = pd.read_csv(
            SOURCE_DIR / "a_share_healthcare_prices_qfq_wide.csv",
            usecols=["trade_date"],
        )["trade_date"]
        END_DATE = pd.to_datetime(source_dates, errors="raise").max().strftime("%Y%m%d")
    print(f"Risk model data end date: {END_DATE}")
    run(args.refresh_membership)
