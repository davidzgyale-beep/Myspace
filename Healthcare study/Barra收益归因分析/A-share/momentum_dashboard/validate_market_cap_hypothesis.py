#!/usr/bin/env python3
"""Validate market-cap segmentation with historical point-in-time data."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
OUTPUT_PATH = APP_DIR / "data" / "market_cap_validation.csv"
THRESHOLDS = (50, 75, 100, 125, 150, 200)


def percentile(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True, na_option="keep")


def rank_ic(frame: pd.DataFrame, signal: str, outcome: str) -> float:
    by_date = frame.groupby("date").apply(
        lambda group: group[signal].rank().corr(group[outcome].rank()),
        include_groups=False,
    )
    return float(by_date.mean())


def build_panel(source_dir: Path) -> pd.DataFrame:
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
    subindustry = universe.set_index("ts_code")["healthcare_subindustry"]
    basics = pd.read_csv(
        source_dir / "a_share_healthcare_daily_basic_long.csv",
        usecols=["ts_code", "trade_date", "total_mv", "pe_ttm", "pb"],
    )
    basics["trade_date"] = pd.to_datetime(basics["trade_date"].astype("string"))

    def basic_panel(column: str) -> pd.DataFrame:
        return (
            basics.pivot(index="trade_date", columns="ts_code", values=column)
            .reindex(index=prices.index, columns=prices.columns)
            .ffill(limit=5)
        )

    market_cap = basic_panel("total_mv") / 10_000
    pe_ttm = basic_panel("pe_ttm")
    pb = basic_panel("pb")
    daily_returns = prices.pct_change(fill_method=None)
    panels: list[pd.DataFrame] = []

    # Non-overlapping 20-session observations reduce serial dependence.
    for position in range(120, len(prices) - 20, 20):
        close = prices.iloc[position]
        market_component = 0.0
        subindustry_component = 0.0
        for sessions, weight in {5: 0.10, 20: 0.30, 60: 0.35, 120: 0.15}.items():
            returns = close / prices.iloc[position - sessions] - 1
            market_component += percentile(returns) * weight
            subindustry_component += returns.groupby(subindustry).rank(pct=True) * weight

        ma20 = prices.iloc[position - 19 : position + 1].mean()
        ma60 = prices.iloc[position - 59 : position + 1].mean()
        high60 = prices.iloc[position - 59 : position + 1].max()
        ma20_gap = close / ma20 - 1
        ma60_gap = close / ma60 - 1
        drawdown60 = close / high60 - 1
        trend = (
            market_component * 0.65
            + subindustry_component * 0.25
            + (ma20_gap.clip(-0.20, 0.20) + 0.20) / 0.40 * 0.05
            + (drawdown60.clip(-0.30, 0) + 0.30) / 0.30 * 0.05
        ) * 100
        overheat = (
            percentile(close / prices.iloc[position - 20] - 1) * 0.30
            + percentile(ma20_gap) * 0.35
            + percentile(ma60_gap) * 0.20
            + percentile(drawdown60) * 0.15
        ) * 100
        volatility = daily_returns.iloc[position - 19 : position + 1].std() * np.sqrt(252)
        risk = overheat * 0.70 + percentile(volatility) * 100 * 0.20

        pe = pe_ttm.iloc[position]
        pb_value = pb.iloc[position]
        pe_rank = pe.where(pe > 0).groupby(subindustry).rank(pct=True)
        pb_rank = pb_value.where(pb_value > 0).groupby(subindustry).rank(pct=True)
        pe_weight = (pe > 0).astype(float) * 0.60
        pb_weight = (pb_value > 0).astype(float) * 0.40
        valuation_weight = pe_weight + pb_weight
        valuation = (
            (
                (1 - pe_rank.fillna(0)) * pe_weight
                + (1 - pb_rank.fillna(0)) * pb_weight
            )
            / valuation_weight
            * (0.75 + 0.25 * valuation_weight)
            * 100
        ).where(valuation_weight > 0)

        future_return = prices.iloc[position + 20] / close - 1
        future_path = prices.iloc[position + 1 : position + 21].div(close, axis=1) - 1
        future_drawdown = (-future_path.min()).clip(lower=0)
        panels.append(
            pd.DataFrame(
                {
                    "date": prices.index[position],
                    "ts_code": prices.columns,
                    "market_cap_100m": market_cap.iloc[position].values,
                    "trend": trend.values,
                    "risk": risk.values,
                    "valuation": valuation.values,
                    "future_return": future_return.values,
                    "future_drawdown": future_drawdown.values,
                }
            )
        )

    return pd.concat(panels, ignore_index=True).dropna(
        subset=["market_cap_100m", "trend", "risk", "future_return", "future_drawdown"]
    )


def validate(panel: pd.DataFrame) -> pd.DataFrame:
    results = []
    for threshold in THRESHOLDS:
        for segment, group in (
            ("小市值", panel[panel["market_cap_100m"] < threshold]),
            ("中大市值", panel[panel["market_cap_100m"] >= threshold]),
        ):
            top_trend = group[
                group.groupby("date")["trend"].rank(pct=True) >= 0.50
            ]
            results.append(
                {
                    "threshold_100m": threshold,
                    "segment": segment,
                    "observation_count": len(group),
                    "median_cross_section_count": int(group.groupby("date").size().median()),
                    "trend_forward_20d_rank_ic": rank_ic(group, "trend", "future_return"),
                    "valuation_forward_20d_rank_ic": rank_ic(
                        group.dropna(subset=["valuation"]), "valuation", "future_return"
                    ),
                    "risk_forward_20d_drawdown_rank_ic": rank_ic(group, "risk", "future_drawdown"),
                    "risk_top_trend_forward_20d_drawdown_rank_ic": rank_ic(
                        top_trend, "risk", "future_drawdown"
                    ),
                }
            )
    return pd.DataFrame(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    output = validate(build_panel(args.source_dir.resolve()))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(output)} validation rows to {OUTPUT_PATH}")
