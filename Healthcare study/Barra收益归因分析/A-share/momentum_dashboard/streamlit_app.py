"""Public Streamlit dashboard for the 310-stock A-share healthcare universe."""

from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
GROUP_COLORS = {"A": "#D94B4B", "B": "#D89B2B", "C": "#7A8793"}
TEMP_COLORS = {"过热": "#C93B3B", "偏热": "#E58B32", "中性": "#4E7FA8", "偏冷": "#62A87C"}

st.set_page_config(page_title="A股医疗动量看板", page_icon=":material/query_stats:", layout="wide")


@st.cache_data(show_spinner="正在载入动量快照…")
def load_snapshot() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    rankings = pd.read_csv(DATA_DIR / "momentum_snapshot.csv", parse_dates=["price_date"])
    history = pd.read_csv(DATA_DIR / "price_history.csv.gz", parse_dates=["trade_date"])
    industries = pd.read_csv(DATA_DIR / "subindustry_snapshot.csv")
    metadata = json.loads((DATA_DIR / "metadata.json").read_text(encoding="utf-8"))
    return rankings, history, industries, metadata


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.1%}"


def normalized_history(history: pd.DataFrame, codes: list[str], sessions: int) -> pd.DataFrame:
    selected = history[history["ts_code"].isin(codes)].copy()
    selected = selected.sort_values(["ts_code", "trade_date"]).groupby("ts_code", as_index=False).tail(sessions)
    selected["normalized"] = selected.groupby("ts_code")["close_qfq"].transform(lambda s: s / s.iloc[0] * 100)
    return selected


rankings, history, industries, meta = load_snapshot()
name_map = rankings.set_index("ts_code")["name"].to_dict()
all_industries = sorted(rankings["healthcare_subindustry"].dropna().unique())

with st.sidebar:
    st.subheader("全局筛选", anchor=False)
    selected_industries = st.multiselect(
        "医疗子行业", all_industries, default=all_industries, placeholder="选择子行业"
    )
    selected_groups = st.pills(
        "分组", ["A", "B", "C"], default=["A", "B", "C"], selection_mode="multi"
    )
    market_cap_max = int(np.ceil(rankings["market_cap_100m"].max() / 100) * 100)
    market_cap_range = st.slider(
        "总市值（亿元）",
        min_value=0,
        max_value=market_cap_max,
        value=(0, market_cap_max),
        step=10,
    )
    search = st.text_input("搜索股票", placeholder="输入名称或代码")
    st.caption(f"行情截止 {meta['as_of_date']} · 方法版本 {meta['methodology_version']}")

filtered = rankings[
    rankings["healthcare_subindustry"].isin(selected_industries)
    & rankings["group"].isin(selected_groups or [])
    & rankings["market_cap_100m"].fillna(0).between(*market_cap_range)
].copy()
if search:
    term = search.strip().lower()
    filtered = filtered[
        filtered["name"].fillna("").str.lower().str.contains(term, regex=False)
        | filtered["ts_code"].str.lower().str.contains(term, regex=False)
    ]

st.title(":material/query_stats: A股医疗动量看板")
st.caption(
    f"覆盖 {meta['stock_count']} 只A股医疗相关股票、{meta['subindustry_count']} 个子行业。"
    "动量衡量趋势强弱，过热度衡量追高风险；二者应结合使用。"
)

with st.container(horizontal=True):
    st.metric("当前样本", f"{len(filtered)} 只", border=True)
    st.metric("A组", f"{(filtered['group'] == 'A').sum()} 只", border=True)
    st.metric("站上60日均线", pct(filtered["above_ma60"].mean()), border=True)
    st.metric("20日收益中位数", pct(filtered["ret_20d"].median()), border=True)
    st.metric("过热股票", f"{(filtered['temperature'] == '过热').sum()} 只", border=True)

overview_tab, ranking_tab, stock_tab, method_tab = st.tabs(
    ["市场总览", "全量排名", "个股透视", "评分方法"]
)

with overview_tab:
    left, right = st.columns([1.35, 1], gap="medium")
    with left.container(border=True):
        st.subheader("动量—过热分布", anchor=False)
        scatter = (
            alt.Chart(filtered)
            .mark_circle(opacity=0.78, stroke="white", strokeWidth=0.5)
            .encode(
                x=alt.X("momentum_score:Q", title="动量分", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("overheat_score:Q", title="过热分", scale=alt.Scale(domain=[0, 100])),
                size=alt.Size("market_cap_100m:Q", title="总市值（亿元）", scale=alt.Scale(range=[35, 850])),
                color=alt.Color("group:N", title="分组", scale=alt.Scale(domain=list(GROUP_COLORS), range=list(GROUP_COLORS.values()))),
                tooltip=[
                    alt.Tooltip("name:N", title="股票"), alt.Tooltip("ts_code:N", title="代码"),
                    alt.Tooltip("healthcare_subindustry:N", title="子行业"),
                    alt.Tooltip("momentum_score:Q", title="动量分", format=".1f"),
                    alt.Tooltip("overheat_score:Q", title="过热分", format=".1f"),
                    alt.Tooltip("ret_20d:Q", title="20日收益", format=".1%"),
                    alt.Tooltip("ret_60d:Q", title="60日收益", format=".1%"),
                ],
            )
            .properties(height=430)
            .interactive()
        )
        st.altair_chart(scatter)

    with right.container(border=True):
        st.subheader("子行业热度", anchor=False)
        visible_industries = industries[industries["healthcare_subindustry"].isin(selected_industries)].head(14)
        bars = (
            alt.Chart(visible_industries)
            .mark_bar(cornerRadiusEnd=3)
            .encode(
                x=alt.X("median_momentum:Q", title="动量分中位数", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("healthcare_subindustry:N", title=None, sort="-x"),
                color=alt.Color("median_ret_20d:Q", title="20日收益中位数", scale=alt.Scale(scheme="redblue", domainMid=0)),
                tooltip=[
                    alt.Tooltip("healthcare_subindustry:N", title="子行业"),
                    alt.Tooltip("stock_count:Q", title="股票数"),
                    alt.Tooltip("median_momentum:Q", title="动量中位数", format=".1f"),
                    alt.Tooltip("median_ret_20d:Q", title="20日收益", format=".1%"),
                    alt.Tooltip("above_ma60_pct:Q", title="站上60日均线", format=".0%"),
                ],
            )
            .properties(height=430)
        )
        st.altair_chart(bars)

    with st.container(border=True):
        st.subheader("领涨与风险提示", anchor=False)
        col_a, col_b, col_c = st.columns(3)
        top_a = filtered[filtered["group"] == "A"].nsmallest(8, "market_rank")
        hot = filtered.nlargest(8, "overheat_score")
        weak = filtered.nlargest(8, "market_rank")
        with col_a:
            st.markdown("**A组趋势领先**")
            st.dataframe(top_a[["market_rank", "name", "healthcare_subindustry", "momentum_score", "ret_20d"]], hide_index=True, height=300)
        with col_b:
            st.markdown("**过热度最高**")
            st.dataframe(hot[["name", "healthcare_subindustry", "overheat_score", "ma20_gap", "drawdown_60d"]], hide_index=True, height=300)
        with col_c:
            st.markdown("**动量尾部**")
            st.dataframe(weak[["market_rank", "name", "healthcare_subindustry", "momentum_score", "ret_60d"]], hide_index=True, height=300)

with ranking_tab:
    st.subheader("310只股票完整排名", anchor=False)
    st.caption("点击表头排序；可用左侧筛选器缩小范围。排名和导出内容使用同一份快照。")
    table = filtered[
        [
            "market_rank", "group", "name", "ts_code", "healthcare_subindustry", "subindustry_rank",
            "momentum_score", "overheat_score", "temperature", "ret_5d", "ret_20d", "ret_60d",
            "ret_120d", "ret_250d", "ma20_gap", "ma60_gap", "drawdown_60d", "market_cap_100m",
        ]
    ].copy()
    st.dataframe(
        table,
        hide_index=True,
        height=650,
        column_config={
            "market_rank": st.column_config.NumberColumn("总排名", pinned=True, format="%d"),
            "group": st.column_config.TextColumn("分组", pinned=True),
            "name": st.column_config.TextColumn("股票", pinned=True),
            "ts_code": "代码", "healthcare_subindustry": "子行业", "subindustry_rank": "行业排名",
            "momentum_score": st.column_config.ProgressColumn("动量分", min_value=0, max_value=100, format="%.1f"),
            "overheat_score": st.column_config.ProgressColumn("过热分", min_value=0, max_value=100, format="%.1f"),
            "temperature": "温度", "ret_5d": st.column_config.NumberColumn("5日", format="percent"),
            "ret_20d": st.column_config.NumberColumn("20日", format="percent"),
            "ret_60d": st.column_config.NumberColumn("60日", format="percent"),
            "ret_120d": st.column_config.NumberColumn("120日", format="percent"),
            "ret_250d": st.column_config.NumberColumn("250日", format="percent"),
            "ma20_gap": st.column_config.NumberColumn("距MA20", format="percent"),
            "ma60_gap": st.column_config.NumberColumn("距MA60", format="percent"),
            "drawdown_60d": st.column_config.NumberColumn("距60日高点", format="percent"),
            "market_cap_100m": st.column_config.NumberColumn("总市值(亿)", format="%.0f"),
        },
    )
    st.download_button(
        "下载当前筛选结果", table.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"a_share_healthcare_momentum_{meta['as_of_date']}.csv", mime="text/csv",
        icon=":material/download:",
    )

with stock_tab:
    options = filtered.sort_values("market_rank").apply(lambda r: f"{r['name']} · {r['ts_code']}", axis=1).tolist()
    if not options:
        st.info("当前筛选条件下没有股票。")
    else:
        selected_label = st.selectbox("选择股票", options)
        selected_code = selected_label.rsplit(" · ", 1)[1]
        row = rankings.loc[rankings["ts_code"] == selected_code].iloc[0]
        with st.container(horizontal=True):
            st.metric("总排名", f"{int(row['market_rank'])} / {len(rankings)}", border=True)
            st.metric("分组", row["group"], border=True)
            st.metric("动量分", f"{row['momentum_score']:.1f}", border=True)
            st.metric("过热分", f"{row['overheat_score']:.1f}", delta=row["temperature"], delta_color="off", border=True)
            st.metric("20日收益", pct(row["ret_20d"]), border=True)
        horizon = st.segmented_control("走势区间", ["60日", "120日", "250日"], default="120日", required=True)
        sessions = {"60日": 60, "120日": 120, "250日": 250}[horizon]
        selected_history = normalized_history(history, [selected_code], sessions)
        selected_history["股票"] = row["name"]
        line = (
            alt.Chart(selected_history)
            .mark_line(color="#D94B4B", strokeWidth=2.5)
            .encode(
                x=alt.X("trade_date:T", title=None), y=alt.Y("normalized:Q", title="区间起点=100", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("trade_date:T", title="日期"), alt.Tooltip("normalized:Q", title="指数", format=".1f")],
            )
            .properties(height=390)
            .interactive()
        )
        st.altair_chart(line)
        st.caption(
            f"{row['name']}属于{row['healthcare_subindustry']}，行业内排名 "
            f"{int(row['subindustry_rank'])}/{int(row['subindustry_count'])}；"
            f"距20日均线 {pct(row['ma20_gap'])}，距60日高点 {pct(row['drawdown_60d'])}。"
        )

with method_tab:
    st.subheader("如何阅读", anchor=False)
    st.markdown(
        """
        - **动量分（0–100）**：综合5/20/60/120日收益的全市场排名与子行业内排名，并加入均线和距高点确认。中期窗口权重更高。
        - **过热分（0–100）**：综合20日涨幅、偏离20/60日均线程度和接近60日高点程度。高分表示趋势强但追高风险也高。
        - **A组**：动量分不低于70、20/60日趋势同时为正、站上20/60日均线，且过热分低于85。
        - **B组**：动量分不低于40且20日跌幅不超过5%，属于观察和等待确认区。
        - **C组**：趋势较弱、近期明显回撤，或历史数据不足。
        """
    )
    st.warning("本看板基于历史价格的横截面排序，不含盈利预测、估值安全边际或实时新闻判断，不构成投资建议。")
    st.caption("公开部署版只包含计算后的数据快照，不包含Tushare密钥。")
