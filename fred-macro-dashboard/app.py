"""Streamlit entry point for the FRED macro dashboard.

Run with:
    streamlit run app.py
    streamlit run app.py -- --refresh   # force-refresh every default series on startup
"""

import argparse
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import transform
from fetch import FredRequestError, MissingAPIKeyError, get_series

TRANSFORM_LABELS = {
    "Level": transform.LEVEL,
    "% Change": transform.PCT_CHANGE,
    "YoY % Change": transform.YOY,
}


def _parse_cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args, _unknown = parser.parse_known_args(sys.argv[1:])
    return args


@st.cache_data(show_spinner=False)
def _load_series(series_id: str, refresh_token: int) -> pd.DataFrame:
    return get_series(series_id, force_refresh=refresh_token > 0)


def _init_state():
    if "refresh_token" not in st.session_state:
        st.session_state.refresh_token = 1 if _parse_cli_args().refresh else 0


def main():
    st.set_page_config(page_title="FRED Macro Dashboard", layout="wide")
    _init_state()

    st.title("FRED Macro Dashboard")

    with st.sidebar:
        st.header("Controls")
        selected_ids = st.multiselect(
            "Series",
            options=list(config.SERIES.keys()),
            default=list(config.SERIES.keys()),
            format_func=lambda sid: f"{sid} – {config.SERIES[sid]}",
        )
        transform_label = st.radio("View", list(TRANSFORM_LABELS.keys()))
        transform_mode = TRANSFORM_LABELS[transform_label]

        if st.button("Refresh selected from FRED"):
            st.session_state.refresh_token += 1
            st.cache_data.clear()

    if not selected_ids:
        st.info("Select at least one series from the sidebar.")
        return

    raw_data = {}
    errors = {}
    for sid in selected_ids:
        try:
            raw_data[sid] = _load_series(sid, st.session_state.refresh_token)
        except MissingAPIKeyError as exc:
            st.error(f"**Missing API key.** {exc}")
            st.stop()
        except FredRequestError as exc:
            errors[sid] = str(exc)

    for sid, message in errors.items():
        st.warning(f"Couldn't load {sid}: {message}")

    if not raw_data:
        st.stop()

    all_dates = pd.concat([df["date"] for df in raw_data.values()])
    min_date, max_date = all_dates.min().date(), all_dates.max().date()
    with st.sidebar:
        date_range = st.slider(
            "Date range",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date),
        )

    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])

    st.subheader("Summary")
    summary_cols = st.columns(len(raw_data))
    for col, (sid, df) in zip(summary_cols, raw_data.items()):
        windowed = df[(df["date"] >= start) & (df["date"] <= end)]
        summary = transform.latest_summary(windowed)
        with col:
            st.metric(
                label=f"{sid}",
                value=(
                    f"{summary['latest_value']:.2f}"
                    if summary["latest_value"] is not None
                    else "n/a"
                ),
                delta=(
                    f"{summary['change']:.2f}"
                    if summary["change"] is not None
                    else None
                ),
                help=config.SERIES[sid],
            )

    st.subheader(transform_label)
    for sid, df in raw_data.items():
        windowed = df[(df["date"] >= start) & (df["date"] <= end)]
        transformed = transform.apply_transform(windowed, transform_mode)
        fig = px.line(
            transformed,
            x="date",
            y="value",
            title=f"{sid} – {config.SERIES[sid]}",
            labels={"date": "Date", "value": transform_label},
        )
        fig.update_traces(hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}<extra></extra>")
        st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
