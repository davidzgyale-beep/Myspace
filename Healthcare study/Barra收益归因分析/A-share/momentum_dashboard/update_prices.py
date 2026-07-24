#!/usr/bin/env python3
"""Incrementally update healthcare price caches and rebuild derived price files."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = APP_DIR.parent / "Full version" / "universe"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN")
DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
ADJ_FIELDS = "ts_code,trade_date,adj_factor"
BASIC_FIELDS = (
    "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,"
    "ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"
)
MARKET_BENCHMARK_CODE = "000300.SH"


def tushare_query(api_name: str, fields: str, **params: str) -> pd.DataFrame:
    if not TUSHARE_TOKEN:
        raise RuntimeError("Set TUSHARE_TOKEN before updating prices")
    payload = json.dumps(
        {"api_name": api_name, "token": TUSHARE_TOKEN, "params": params, "fields": fields},
        ensure_ascii=False,
    )
    result = subprocess.run(
        [
            "curl", "-sS", "-m", "60", "-X", "POST", "https://api.tushare.pro",
            "-H", "Content-Type: application/json", "-d", payload,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    response = json.loads(result.stdout)
    if response.get("code") != 0:
        raise RuntimeError(f"{api_name}: {response.get('msg')}")
    data = response.get("data") or {}
    return pd.DataFrame(data.get("items", []), columns=data.get("fields", []))


def fetch_window(start_date: str, end_date: str, codes: set[str]) -> pd.DataFrame:
    frames = []
    for date in pd.bdate_range(start_date, end_date):
        trade_date = date.strftime("%Y%m%d")
        daily = tushare_query("daily", DAILY_FIELDS, trade_date=trade_date)
        time.sleep(0.2)
        adj = tushare_query("adj_factor", ADJ_FIELDS, trade_date=trade_date)
        time.sleep(0.2)
        if daily.empty or adj.empty:
            print(f"{trade_date}: no market data")
            continue
        merged = daily.merge(adj, on=["ts_code", "trade_date"], how="inner")
        merged = merged[merged["ts_code"].isin(codes)].copy()
        frames.append(merged)
        print(f"{trade_date}: fetched {len(merged)} universe rows")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def update_daily_basic(source_dir: Path, start_date: str, end_date: str, codes: set[str]) -> None:
    frames = []
    for date in pd.bdate_range(start_date, end_date):
        trade_date = date.strftime("%Y%m%d")
        basic = tushare_query("daily_basic", BASIC_FIELDS, trade_date=trade_date)
        basic = basic[basic["ts_code"].isin(codes)].copy()
        if not basic.empty:
            frames.append(basic)
        time.sleep(0.2)
    if not frames:
        raise RuntimeError("No new daily_basic rows fetched")
    path = source_dir / "a_share_healthcare_daily_basic_long.csv"
    existing = pd.read_csv(path)
    combined = pd.concat([existing, *frames], ignore_index=True, sort=False)
    combined["trade_date"] = pd.to_datetime(
        combined["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True),
        format="mixed",
        errors="raise",
    ).dt.strftime("%Y-%m-%d")
    combined = combined.drop_duplicates(["ts_code", "trade_date"], keep="last")
    combined = combined.sort_values(["ts_code", "trade_date"])
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(
        f"Updated daily_basic for {pd.concat(frames)['ts_code'].nunique()} stocks "
        f"through {combined['trade_date'].max()}"
    )


def update_market_benchmark(start_date: str, end_date: str) -> None:
    path = APP_DIR / "data" / "market_benchmark.csv"
    existing = pd.read_csv(path) if path.exists() else pd.DataFrame()
    # Recover the full series if a previous interrupted update left a truncated file.
    query_start = "20190101" if len(existing) < 1000 else start_date
    incoming = tushare_query(
        "index_daily",
        "trade_date,close",
        ts_code=MARKET_BENCHMARK_CODE,
        start_date=query_start,
        end_date=end_date,
    )
    if incoming.empty:
        print("No new CSI 300 benchmark rows")
        return
    if query_start == "20190101":
        existing = pd.DataFrame()
    combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    date_text = combined["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True)
    combined["trade_date"] = pd.to_datetime(
        date_text, format="%Y%m%d", errors="raise"
    ).dt.strftime("%Y%m%d")
    combined["close"] = pd.to_numeric(combined["close"], errors="coerce")
    combined = combined.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Updated CSI 300 benchmark through {combined['trade_date'].max()}")


def update_caches(source_dir: Path, new_rows: pd.DataFrame) -> pd.DataFrame:
    cache_dir = source_dir / "price_cache_by_stock"
    updated = []
    for code, incoming in new_rows.groupby("ts_code"):
        path = cache_dir / f"{code}.csv"
        existing = pd.read_csv(path) if path.exists() else pd.DataFrame()
        combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
        combined["trade_date"] = pd.to_datetime(combined["trade_date"], format="mixed").dt.strftime("%Y-%m-%d")
        combined = combined.drop_duplicates(["ts_code", "trade_date"], keep="last").sort_values("trade_date")
        numeric = ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount", "adj_factor"]
        for col in numeric:
            combined[col] = pd.to_numeric(combined[col], errors="coerce")
        latest_adj = combined["adj_factor"].dropna().iloc[-1]
        for col in ["open", "high", "low", "close"]:
            combined[f"{col}_qfq"] = combined[col] * combined["adj_factor"] / latest_adj
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        updated.append(combined)
    return pd.concat(updated, ignore_index=True)


def rebuild_outputs(source_dir: Path, universe: pd.DataFrame) -> None:
    cache_dir = source_dir / "price_cache_by_stock"
    frames = [pd.read_csv(cache_dir / f"{code}.csv") for code in universe["ts_code"]]
    long_df = pd.concat(frames, ignore_index=True).drop_duplicates(["ts_code", "trade_date"])
    long_df = long_df.sort_values(["ts_code", "trade_date"])
    long_df.to_csv(source_dir / "a_share_healthcare_prices_long.csv", index=False, encoding="utf-8-sig")
    close = long_df.pivot(index="trade_date", columns="ts_code", values="close_qfq").sort_index().sort_index(axis=1)
    close.to_csv(source_dir / "a_share_healthcare_prices_qfq_wide.csv", encoding="utf-8-sig")
    close.pct_change(fill_method=None).to_csv(source_dir / "a_share_healthcare_returns_wide.csv", encoding="utf-8-sig")

    sub_map = universe.set_index("ts_code")["healthcare_subindustry"]
    returns = close.pct_change(fill_method=None)
    sub_indices = {}
    for subindustry, codes in sub_map.groupby(sub_map).groups.items():
        valid = [code for code in codes if code in returns.columns]
        sub_indices[subindustry] = (1 + returns[valid].mean(axis=1).fillna(0)).cumprod() * 100
    pd.DataFrame(sub_indices).to_csv(source_dir / "a_share_healthcare_subindustry_indices.csv", encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--start-date", help="YYYYMMDD; defaults to the day after the wide price file")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    universe = pd.read_csv(source_dir / "a_share_healthcare_universe.csv")
    wide = pd.read_csv(source_dir / "a_share_healthcare_prices_qfq_wide.csv", index_col=0)
    start_date = args.start_date or (pd.Timestamp(wide.index.max()) + pd.Timedelta(days=1)).strftime("%Y%m%d")
    codes = set(universe["ts_code"])
    new_rows = fetch_window(start_date, args.end_date, codes)
    if new_rows.empty:
        raise RuntimeError("No new universe rows fetched")
    update_caches(source_dir, new_rows)
    rebuild_outputs(source_dir, universe)
    update_daily_basic(source_dir, start_date, args.end_date, codes)
    update_market_benchmark(start_date, args.end_date)
    print(f"Updated {new_rows['ts_code'].nunique()} stocks through {args.end_date}")


if __name__ == "__main__":
    main()
