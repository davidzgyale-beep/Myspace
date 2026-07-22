#!/usr/bin/env python3
"""Update half-year report appointment dates for the healthcare dashboard."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_NAME = "RPT_PUBLIC_BS_APPOIN"
PAGE_SIZE = 500


def fetch_page(report_date: str, page_number: int) -> dict:
    query = urllib.parse.urlencode(
        {
            "reportName": REPORT_NAME,
            "columns": "ALL",
            "filter": f"(REPORT_DATE='{report_date}')",
            "pageNumber": page_number,
            "pageSize": PAGE_SIZE,
            "sortColumns": "APPOINT_PUBLISH_DATE",
            "sortTypes": 1,
            "source": "WEB",
            "client": "WEB",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not payload.get("success") or not payload.get("result"):
        raise RuntimeError(f"Appointment API failed: {payload.get('message', 'unknown error')}")
    return payload["result"]


def fetch_appointments(report_date: str) -> pd.DataFrame:
    first = fetch_page(report_date, 1)
    rows = list(first.get("data") or [])
    for page_number in range(2, int(first["pages"]) + 1):
        time.sleep(0.15)
        rows.extend(fetch_page(report_date, page_number).get("data") or [])
    return pd.DataFrame(rows)


def build_calendar(report_year: int) -> pd.DataFrame:
    rankings = pd.read_csv(DATA_DIR / "momentum_snapshot.csv")
    report_date = f"{report_year}-06-30"
    appointments = fetch_appointments(report_date)
    if appointments.empty:
        raise RuntimeError(f"No appointment data returned for {report_date}")

    selected = appointments[
        [
            "SECUCODE",
            "FIRST_APPOINT_DATE",
            "FIRST_CHANGE_DATE",
            "SECOND_CHANGE_DATE",
            "THIRD_CHANGE_DATE",
            "APPOINT_PUBLISH_DATE",
            "ACTUAL_PUBLISH_DATE",
            "IS_PUBLISH",
            "REPORT_TYPE_NAME",
            "INFO_CODE",
            "EITIME",
        ]
    ].rename(
        columns={
            "SECUCODE": "ts_code",
            "FIRST_APPOINT_DATE": "first_appointment_date",
            "FIRST_CHANGE_DATE": "first_change_date",
            "SECOND_CHANGE_DATE": "second_change_date",
            "THIRD_CHANGE_DATE": "third_change_date",
            "APPOINT_PUBLISH_DATE": "appointment_date",
            "ACTUAL_PUBLISH_DATE": "actual_publish_date",
            "IS_PUBLISH": "is_published",
            "REPORT_TYPE_NAME": "report_type",
            "INFO_CODE": "announcement_id",
            "EITIME": "source_updated_at",
        }
    )
    date_columns = [
        "first_appointment_date",
        "first_change_date",
        "second_change_date",
        "third_change_date",
        "appointment_date",
        "actual_publish_date",
    ]
    for column in date_columns:
        selected[column] = pd.to_datetime(selected[column], errors="coerce").dt.date
    selected["is_published"] = selected["is_published"].astype("string").eq("1")
    selected["appointment_changed"] = selected[
        ["first_change_date", "second_change_date", "third_change_date"]
    ].notna().any(axis=1) | (
        selected["appointment_date"] != selected["first_appointment_date"]
    )

    calendar = rankings[
        ["ts_code", "name", "healthcare_subindustry", "market_cap_100m"]
    ].merge(selected, on="ts_code", how="left", validate="one_to_one")
    calendar["importance_rank"] = calendar["market_cap_100m"].rank(
        method="first", ascending=False, na_option="bottom"
    ).astype("int64")
    calendar["is_key_stock"] = calendar["importance_rank"] <= 30
    calendar["report_year"] = report_year
    calendar = calendar.sort_values(
        ["appointment_date", "importance_rank"], na_position="last"
    )
    return calendar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-year",
        type=int,
        default=date.today().year,
        help="Half-year report year; defaults to the current year",
    )
    args = parser.parse_args()
    calendar = build_calendar(args.report_year)
    output = DATA_DIR / "half_year_report_calendar.csv"
    calendar.to_csv(output, index=False, encoding="utf-8-sig")
    covered = int(calendar["appointment_date"].notna().sum())
    print(f"Updated {covered}/{len(calendar)} healthcare appointments for {args.report_year}")


if __name__ == "__main__":
    main()
