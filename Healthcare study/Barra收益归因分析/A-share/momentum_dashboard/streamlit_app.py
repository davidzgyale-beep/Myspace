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

st.set_page_config(page_title="A股医疗研究看板", page_icon=":material/query_stats:", layout="wide")


@st.cache_data(show_spinner="正在载入研究快照…")
def load_snapshot() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    rankings = pd.read_csv(DATA_DIR / "momentum_snapshot.csv", parse_dates=["price_date", "valuation_as_of_date"])
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


def set_all_industries() -> None:
    st.session_state["selected_industries"] = list(ALL_INDUSTRIES)


def clear_industries() -> None:
    st.session_state["selected_industries"] = []


def apply_preset() -> None:
    st.session_state["selected_industries"] = list(INDUSTRY_PRESETS[st.session_state["industry_preset"]])


def apply_industry_batch() -> None:
    current = set(st.session_state.get("selected_industries", []))
    additions = set(st.session_state.get("industry_add", []))
    removals = set(st.session_state.get("industry_remove", []))
    st.session_state["selected_industries"] = sorted((current | additions) - removals)


rankings, history, industries, meta = load_snapshot()
ALL_INDUSTRIES = sorted(rankings["healthcare_subindustry"].dropna().unique().tolist())
top_industries = industries.sort_values("median_momentum", ascending=False)["healthcare_subindustry"].head(7).tolist()
INDUSTRY_PRESETS = {
    "全部子行业": ALL_INDUSTRIES,
    "趋势领先前7": top_industries,
    "CXO与器械": ["CXO/CDMO", "医疗设备", "医疗耗材", "IVD/体外诊断", "医疗器械其他"],
    "创新药与生物": ["化学制药/创新药", "生物制品/创新药", "生物制品/生物科技", "疫苗"],
    "防御与流通": ["中药", "医药流通", "零售药房", "血制品", "营养品/维生素"],
}
st.session_state.setdefault("selected_industries", list(ALL_INDUSTRIES))
st.session_state.setdefault("industry_preset", "全部子行业")

with st.sidebar:
    st.subheader("筛选与批量操作", anchor=False)
    st.caption("先用预设或全选/清空，再用批量加入/删除做微调。")
    st.selectbox("子行业预设", list(INDUSTRY_PRESETS), key="industry_preset")
    with st.container(horizontal=True):
        st.button("应用预设", on_click=apply_preset, icon=":material/bookmark:")
        st.button("全选", on_click=set_all_industries, icon=":material/select_all:")
        st.button("清空", on_click=clear_industries, icon=":material/deselect:")

    st.multiselect("已选子行业", ALL_INDUSTRIES, key="selected_industries", placeholder="选择子行业")
    with st.form("industry_batch_form", border=True):
        current = set(st.session_state.get("selected_industries", []))
        add_options = [x for x in ALL_INDUSTRIES if x not in current]
        remove_options = sorted(current)
        st.multiselect("批量加入", add_options, key="industry_add", placeholder="可多选")
        st.multiselect("批量删除", remove_options, key="industry_remove", placeholder="可多选")
        st.form_submit_button("应用批量修改", on_click=apply_industry_batch, icon=":material/tune:")

    selected_groups = st.pills("股票标签", ["A", "B", "C"], default=["A", "B", "C"], key="selected_groups", selection_mode="multi")
    market_cap_max = int(np.ceil(rankings["market_cap_100m"].max() / 100) * 100)
    market_cap_range = st.slider("总市值（亿元）", 0, market_cap_max, (0, market_cap_max), 10)
    signal_choices = ["全部信号", "强趋势低过热", "强趋势高过热", "估值便宜待确认", "弱趋势/数据不足"]
    signal_filter = st.selectbox("研究信号", signal_choices)
    search = st.text_input("搜索股票", placeholder="输入名称或代码")
    st.caption(f"行情截止 {meta['as_of_date']} · 估值截止 {meta.get('valuation_as_of_date', '未知')} · 方法 {meta['methodology_version']}")

filtered = rankings[
    rankings["healthcare_subindustry"].isin(st.session_state.get("selected_industries", []))
    & rankings["group"].isin(selected_groups or [])
    & rankings["market_cap_100m"].fillna(0).between(*market_cap_range)
].copy()
if signal_filter != "全部信号":
    filtered = filtered[filtered["signal_label"] == signal_filter]
if search:
    term = search.strip().lower()
    filtered = filtered[
        filtered["name"].fillna("").str.lower().str.contains(term, regex=False)
        | filtered["ts_code"].str.lower().str.contains(term, regex=False)
    ]

st.title(":material/query_stats: A股医疗研究看板")
st.caption(
    f"覆盖 {meta['stock_count']} 只股票、{meta['subindustry_count']} 个子行业。"
    "趋势强度回答‘涨得是否强’，估值分回答‘相对是否便宜’，追高风险回答‘现在是否拥挤’。"
)

with st.container(horizontal=True):
    st.metric("当前样本", f"{len(filtered)} 只", border=True)
    st.metric("强趋势低过热", f"{(filtered['signal_label'] == '强趋势低过热').sum()} 只", border=True)
    st.metric("估值便宜待确认", f"{(filtered['signal_label'] == '估值便宜待确认').sum()} 只", border=True)
    st.metric("20日收益中位数", pct(filtered["ret_20d"].median()), border=True)
    st.metric("高追高风险", f"{(filtered['overheat_score'] >= 90).sum()} 只", border=True)

overview_tab, ranking_tab, stock_tab, method_tab = st.tabs(["市场状态", "股票排名", "个股拆解", "评分方法"])

with overview_tab:
    st.subheader("先看结论", anchor=False)
    col1, col2 = st.columns(2, gap="medium")
    with col1.container(border=True):
        st.markdown("**强趋势、追高风险相对可控**")
        candidates = filtered[filtered["signal_label"] == "强趋势低过热"].nsmallest(10, "market_rank")
        st.dataframe(candidates[["market_rank", "name", "healthcare_subindustry", "momentum_score", "valuation_score", "risk_score"]], hide_index=True, height=300)
    with col2.container(border=True):
        st.markdown("**估值便宜，但趋势尚未确认**")
        value_watch = filtered[filtered["signal_label"] == "估值便宜待确认"].nlargest(10, "valuation_score")
        st.dataframe(value_watch[["name", "healthcare_subindustry", "valuation_score", "momentum_score", "ret_20d", "valuation_status"]], hide_index=True, height=300)

    with st.container(border=True):
        st.subheader("趋势强度与追高风险", anchor=False)
        scatter_base = alt.Chart(filtered).mark_circle(opacity=0.8, stroke="white", strokeWidth=0.5).encode(
            x=alt.X("momentum_score:Q", title="趋势强度", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("overheat_score:Q", title="追高风险", scale=alt.Scale(domain=[0, 100])),
            size=alt.Size("market_cap_100m:Q", title="总市值（亿元）", scale=alt.Scale(range=[35, 850])),
            color=alt.Color("group:N", title="标签", scale=alt.Scale(domain=list(GROUP_COLORS), range=list(GROUP_COLORS.values()))),
            tooltip=[alt.Tooltip("name:N", title="股票"), alt.Tooltip("ts_code:N", title="代码"), alt.Tooltip("healthcare_subindustry:N", title="子行业"), alt.Tooltip("signal_label:N", title="研究信号"), alt.Tooltip("momentum_score:Q", title="趋势强度", format=".1f"), alt.Tooltip("valuation_score:Q", title="估值分", format=".1f"), alt.Tooltip("overheat_score:Q", title="追高风险", format=".1f")],
        )
        rules = alt.layer(
            alt.Chart(pd.DataFrame({"x": [70]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(x="x:Q"),
            alt.Chart(pd.DataFrame({"y": [90]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(y="y:Q"),
        )
        st.altair_chart((scatter_base + rules).properties(height=430).interactive())
        st.caption("右下区域通常代表‘趋势强、尚未极端过热’；右上代表‘趋势强但追高风险高’。虚线分别为趋势70、风险90。")

    with st.container(border=True):
        st.subheader("子行业状态", anchor=False)
        industry_view = industries[industries["healthcare_subindustry"].isin(st.session_state.get("selected_industries", []))].copy()
        industry_view["state"] = np.select([industry_view["median_momentum"] >= 60, industry_view["median_momentum"] >= 40], ["强", "中性"], default="弱")
        bars = alt.Chart(industry_view).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("median_momentum:Q", title="趋势强度中位数", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("healthcare_subindustry:N", title=None, sort="-x"),
            color=alt.Color("state:N", title="状态", scale=alt.Scale(domain=["强", "中性", "弱"], range=["#C8423B", "#D69B35", "#7A8793"])),
            tooltip=[alt.Tooltip("healthcare_subindustry:N", title="子行业"), alt.Tooltip("stock_count:Q", title="股票数"), alt.Tooltip("median_momentum:Q", title="趋势中位数", format=".1f"), alt.Tooltip("median_ret_20d:Q", title="20日收益", format=".1%"), alt.Tooltip("group_a_count:Q", title="A组数量")],
        ).properties(height=max(300, 22 * len(industry_view)))
        st.altair_chart(bars)

with ranking_tab:
    st.subheader("股票排名与研究信号", anchor=False)
    st.caption("默认只显示核心字段；需要更多指标时可下载完整筛选结果。")
    table = filtered[["market_rank", "name", "ts_code", "healthcare_subindustry", "signal_label", "group", "momentum_score", "valuation_score", "risk_score", "overheat_score", "ret_20d", "ret_60d", "latest_pe_ttm", "latest_pb", "valuation_status", "market_cap_100m"]].copy()
    st.dataframe(table, hide_index=True, height=650, column_config={
        "market_rank": st.column_config.NumberColumn("总排名", pinned=True, format="%d"),
        "name": st.column_config.TextColumn("股票", pinned=True), "ts_code": "代码", "healthcare_subindustry": "子行业", "signal_label": "研究信号", "group": "趋势标签",
        "momentum_score": st.column_config.ProgressColumn("趋势强度", min_value=0, max_value=100, format="%.1f"),
        "valuation_score": st.column_config.ProgressColumn("估值分", min_value=0, max_value=100, format="%.1f"),
        "risk_score": st.column_config.ProgressColumn("风险分", min_value=0, max_value=100, format="%.1f"),
        "overheat_score": st.column_config.NumberColumn("追高风险", format="%.1f"), "ret_20d": st.column_config.NumberColumn("20日", format="percent"), "ret_60d": st.column_config.NumberColumn("60日", format="percent"),
        "latest_pe_ttm": st.column_config.NumberColumn("PE_TTM", format="%.1f"), "latest_pb": st.column_config.NumberColumn("PB", format="%.2f"), "valuation_status": "估值状态", "market_cap_100m": st.column_config.NumberColumn("总市值(亿)", format="%.0f"),
    })
    st.download_button("下载当前筛选结果", filtered.to_csv(index=False, encoding="utf-8-sig"), file_name=f"a_share_healthcare_research_{meta['as_of_date']}.csv", mime="text/csv", icon=":material/download:")

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
            st.metric("研究信号", row["signal_label"], border=True)
            st.metric("趋势强度", f"{row['momentum_score']:.1f}", border=True)
            st.metric("估值分", "—" if pd.isna(row["valuation_score"]) else f"{row['valuation_score']:.1f}", border=True)
            st.metric("风险分", f"{row['risk_score']:.1f}", border=True)
        detail_left, detail_right = st.columns(2, gap="medium")
        with detail_left.container(border=True):
            st.markdown("**评分拆解**")
            st.write(f"趋势强度：{row['momentum_score']:.1f} · 20日 {pct(row['ret_20d'])} · 60日 {pct(row['ret_60d'])}")
            st.write(f"估值：{row['valuation_status']} · PE {row['latest_pe_ttm']:.1f} · PB {row['latest_pb']:.2f}" if row["valuation_status"] != "估值缺失" else "估值：缺失，未用低估值逻辑加分")
            st.write(f"风险：追高风险 {row['overheat_score']:.1f} · 年化波动率 {pct(row['volatility_20d'])} · 距60日高点 {pct(row['drawdown_60d'])}")
        with detail_right.container(border=True):
            st.markdown("**数据与比较口径**")
            st.write(f"子行业：{row['healthcare_subindustry']} · 行业内趋势排名 {int(row['subindustry_rank'])}/{int(row['subindustry_count'])}")
            st.write(f"价格日期：{row['price_date'].date()} · 估值日期：{row['valuation_as_of_date'].date() if pd.notna(row['valuation_as_of_date']) else '未知'}")
            st.write(f"数据完整度：{row['data_completeness_score']:.0f}/100 · {row['classification_confidence']} 分类置信度")
        horizon = st.segmented_control("走势区间", ["60日", "120日", "250日"], default="120日", required=True)
        selected_history = normalized_history(history, [selected_code], {"60日": 60, "120日": 120, "250日": 250}[horizon])
        line = alt.Chart(selected_history).mark_line(color="#D94B4B", strokeWidth=2.5).encode(x=alt.X("trade_date:T", title=None), y=alt.Y("normalized:Q", title="区间起点=100", scale=alt.Scale(zero=False)), tooltip=[alt.Tooltip("trade_date:T", title="日期"), alt.Tooltip("normalized:Q", title="指数", format=".1f")]).properties(height=390).interactive()
        st.altair_chart(line)

with method_tab:
    st.subheader("评分方法与数据边界", anchor=False)
    st.markdown(
        """
        - **趋势强度**：5/20/60/120日收益的全市场与子行业内排名，叠加均线和距高点确认；20日、60日窗口权重最高。
        - **估值分**：PE_TTM和PB只在所属子行业内比较；正PE权重60%，正PB权重40%；负PE或缺失PE不被当作便宜，估值分会因有效字段不足而降权。
        - **研究信号**：强趋势低过热、强趋势高过热、估值便宜待确认、弱趋势/数据不足。它们是研究优先级，不是买卖评级。
        - **风险分**：追高风险、20日年化波动率和价格数据滞后度的组合；分数越高，风险越高。
        - **质量分暂未启用**：当前快照没有ROE、营收增速、扣非利润增速和结构化新闻字段，因此看板不会假装拥有这些信息。
        """
    )
    st.warning(f"价格截至 {meta['as_of_date']}；估值字段截至 {meta.get('valuation_as_of_date', '未知')}，两者可能存在时点差异。看板用于研究和监控，不构成投资建议。", icon=":material/warning:")
