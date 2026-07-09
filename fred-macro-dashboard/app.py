"""Streamlit entry point for the macro + commodities dashboard.

Run with:
    streamlit run app.py
    streamlit run app.py -- --refresh   # force-refresh every default series on startup
"""

import argparse
import sys

import altair as alt
import pandas as pd
import streamlit as st

import config
import transform
from fetch import FredRequestError, MissingAPIKeyError, get_series

TRANSFORM_LABELS = {
    "Level": transform.LEVEL,
    "% change": transform.PCT_CHANGE,
    "YoY % change": transform.YOY,
}

CHART_HEIGHT = 260
CHART_COLUMNS = 2


def _y_axis_label(series_id: str, transform_mode: str) -> str:
    if transform_mode == transform.LEVEL:
        return config.SERIES[series_id]["unit"]
    return "Percent"


def _make_chart(df: pd.DataFrame, y_label: str, start: pd.Timestamp, end: pd.Timestamp) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X("date:T", title="Date", scale=alt.Scale(domain=[start.isoformat(), end.isoformat()])),
            y=alt.Y("value:Q", title=y_label),
            tooltip=[
                alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
                alt.Tooltip("value:Q", title=y_label, format=".2f"),
            ],
        )
        .properties(height=CHART_HEIGHT)
    )


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
    st.set_page_config(
        page_title="Macro dashboard",
        page_icon=":material/monitoring:",
        layout="wide",
    )
    _init_state()

    st.title("Macro dashboard")

    with st.sidebar:
        st.header("Controls")
        selected_ids = st.multiselect(
            "Series",
            options=list(config.SERIES.keys()),
            default=list(config.SERIES.keys()),
            format_func=lambda sid: f"{sid} – {config.SERIES[sid]['label']}",
        )
        transform_label = st.segmented_control(
            "View",
            list(TRANSFORM_LABELS.keys()),
            default="Level",
        )
        transform_mode = TRANSFORM_LABELS[transform_label or "Level"]

        if st.button("Refresh selected", icon=":material/refresh:"):
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
            st.error(f"**Missing API key.** {exc}", icon=":material/key_off:")
            st.stop()
        except FredRequestError as exc:
            errors[sid] = str(exc)

    for sid, message in errors.items():
        st.warning(f"Couldn't load {sid}: {message}", icon=":material/warning:")

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
    with st.container(horizontal=True):
        for sid, df in raw_data.items():
            windowed = df[(df["date"] >= start) & (df["date"] <= end)]
            summary = transform.latest_summary(windowed)
            st.metric(
                label=sid,
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
                help=config.SERIES[sid]["label"],
                border=True,
                chart_data=windowed["value"].tail(12).tolist() or None,
            )

    st.subheader(transform_label or "Level")
    series_ids = list(raw_data.keys())
    for row_start in range(0, len(series_ids), CHART_COLUMNS):
        row_ids = series_ids[row_start : row_start + CHART_COLUMNS]
        cols = st.columns(CHART_COLUMNS)
        for col, sid in zip(cols, row_ids):
            df = raw_data[sid]
            windowed = df[(df["date"] >= start) & (df["date"] <= end)]
            transformed = transform.apply_transform(windowed, transform_mode)
            y_label = _y_axis_label(sid, transform_mode)
            with col, st.container(border=True, height="stretch"):
                st.markdown(f"**{sid} – {config.SERIES[sid]['label']}**")
                st.altair_chart(_make_chart(transformed, y_label, start, end), width="stretch")


if __name__ == "__main__":
    main()
