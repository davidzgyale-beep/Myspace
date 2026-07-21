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
def load_snapshot() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, dict]:
    rankings = pd.read_csv(DATA_DIR / "momentum_snapshot.csv", parse_dates=["price_date", "valuation_as_of_date"])
    history = pd.read_csv(DATA_DIR / "price_history.csv.gz", parse_dates=["trade_date"])
    industries = pd.read_csv(DATA_DIR / "subindustry_snapshot.csv")
    group_backtest = pd.read_csv(DATA_DIR / "group_backtest_summary.csv")
    group_backtest_yearly = pd.read_csv(DATA_DIR / "group_backtest_yearly.csv")
    group_backtest_metadata = json.loads(
        (DATA_DIR / "group_backtest_metadata.json").read_text(encoding="utf-8")
    )
    metadata = json.loads((DATA_DIR / "metadata.json").read_text(encoding="utf-8"))
    return rankings, history, industries, group_backtest, group_backtest_yearly, group_backtest_metadata, metadata


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


rankings, history, industries, group_backtest, group_backtest_yearly, group_backtest_meta, meta = load_snapshot()
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

overview_tab, backtest_tab, ranking_tab, stock_tab, compare_tab, method_tab = st.tabs(
    ["市场状态", "分组回测", "股票排名", "个股拆解", "个股比较", "评分方法"]
)

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

with backtest_tab:
    st.subheader("过去三年A/B/C分组回测", anchor=False)
    selected_horizon = st.segmented_control(
        "未来收益周期",
        ["5日", "20日", "120日"],
        default="20日",
        required=True,
        key="backtest_horizon",
    )
    horizon_sessions = int(selected_horizon.removesuffix("日"))
    horizon_meta = group_backtest_meta["horizons"][str(horizon_sessions)]
    horizon_summary = group_backtest[group_backtest["horizon_sessions"] == horizon_sessions].copy()
    horizon_yearly = group_backtest_yearly[
        group_backtest_yearly["horizon_sessions"] == horizon_sessions
    ].copy()
    st.caption(
        f"{horizon_meta['start_entry_date']}至{horizon_meta['end_entry_date']}，"
        f"每{horizon_sessions}个交易日形成一次非重叠组合并持有{horizon_sessions}个交易日；"
        "每期先对组内股票等权，再跨期平均。"
    )
    metrics_by_group = horizon_summary.set_index("group")
    with st.container(horizontal=True):
        for group in ["A", "B", "C"]:
            result = metrics_by_group.loc[group]
            st.metric(
                f"{group}组平均未来{horizon_sessions}日收益",
                pct(result["average_forward_return"]),
                f"胜率 {result['win_rate']:.1%}",
                border=True,
            )

    if horizon_sessions == 120:
        st.warning(
            "120日周期只有6–7个独立调仓期，均值容易受少数时期影响；A组仍未领先B/C组，"
            "但这一周期更适合视为方向性证据。",
            icon=":material/warning:",
        )
    else:
        st.warning(
            f"过去三年样本中，A组的未来{horizon_sessions}日平均收益没有领先B/C组。"
            "因此A/B/C应理解为当前趋势状态标签，不应直接解释为未来收益评级。",
            icon=":material/warning:",
        )

    chart_left, chart_right = st.columns(2, gap="medium")
    with chart_left.container(border=True):
        st.markdown("**全样本平均收益与回撤**")
        backtest_long = horizon_summary.melt(
            id_vars=["group"],
            value_vars=["average_forward_return", "average_forward_drawdown"],
            var_name="metric",
            value_name="value",
        )
        backtest_long["metric"] = backtest_long["metric"].map(
            {"average_forward_return": "平均收益", "average_forward_drawdown": "平均最大回撤"}
        )
        result_bars = alt.Chart(backtest_long).mark_bar().encode(
            x=alt.X("group:N", title="分组", sort=["A", "B", "C"]),
            y=alt.Y("value:Q", title=None, axis=alt.Axis(format="%")),
            xOffset="metric:N",
            color=alt.Color("metric:N", title="指标", scale=alt.Scale(range=["#587A95", "#C8423B"])),
            tooltip=[
                alt.Tooltip("group:N", title="分组"),
                alt.Tooltip("metric:N", title="指标"),
                alt.Tooltip("value:Q", title="数值", format=".2%"),
            ],
        ).properties(height=360)
        st.altair_chart(result_bars)

    with chart_right.container(border=True):
        st.markdown(f"**按进入年份拆分的平均未来{horizon_sessions}日收益**")
        yearly_bars = alt.Chart(horizon_yearly).mark_bar().encode(
            x=alt.X("year:O", title="进入年份"),
            y=alt.Y("average_forward_return:Q", title=f"平均未来{horizon_sessions}日收益", axis=alt.Axis(format="%")),
            xOffset="group:N",
            color=alt.Color("group:N", title="分组", scale=alt.Scale(domain=list(GROUP_COLORS), range=list(GROUP_COLORS.values()))),
            tooltip=[
                alt.Tooltip("year:O", title="年份"),
                alt.Tooltip("group:N", title="分组"),
                alt.Tooltip("average_forward_return:Q", title="平均收益", format=".2%"),
                alt.Tooltip("win_rate:Q", title="组合胜率", format=".1%"),
                alt.Tooltip("rebalance_count:Q", title="调仓期数"),
            ],
        ).properties(height=360)
        st.altair_chart(yearly_bars)

    with st.container(border=True):
        st.markdown("**回测明细摘要**")
        st.dataframe(
            horizon_summary,
            hide_index=True,
            column_config={
                "horizon_sessions": None,
                "group": "分组",
                "average_forward_return": st.column_config.NumberColumn(f"平均未来{horizon_sessions}日收益", format="percent"),
                "median_period_return": st.column_config.NumberColumn("期度收益中位数", format="percent"),
                "win_rate": st.column_config.NumberColumn("组合胜率", format="percent"),
                "average_forward_drawdown": st.column_config.NumberColumn("平均最大回撤", format="percent"),
                "rebalance_count": "有效调仓期数",
                "observation_count": "股票观测数",
                "annual_average_dispersion": st.column_config.NumberColumn("年度均值离散度", format="percent"),
            },
        )
        st.caption(
            f"最后一个组合于{horizon_meta['last_exit_date']}退出，共"
            f"{horizon_meta['rebalance_count']}个调仓日期、{horizon_meta['observation_count']:,}个股票观测。"
        )

    with st.expander("回测规则与局限"):
        st.markdown(
            """
            - 每个历史时点只使用当时及此前价格，按当前完全相同的趋势分、过热分和A/B/C阈值重新分类。
            - 5/20/120日都使用与持有期相同的调仓间隔，形成非重叠组合；每个调仓日组内股票等权。
            - 未计交易成本、停牌成交限制、涨跌停和冲击成本；当前310只股票池用于全部历史时期，存在幸存者偏差。
            - A组在部分历史调仓日为空，因此有效期数少于B/C组；120日周期独立样本尤其有限。结果是历史描述，不构成未来收益承诺。
            """
        )

with ranking_tab:
    st.subheader("股票排名与研究信号", anchor=False)
    st.caption("默认只显示核心字段；需要更多指标时可下载完整筛选结果。")
    table = filtered[["market_rank", "name", "ts_code", "healthcare_subindustry", "signal_label", "group", "momentum_score", "valuation_score", "risk_score", "overheat_score", "ret_20d", "ret_60d", "latest_pe_ttm", "latest_pb", "valuation_status", "market_cap_100m"]].copy()
    st.dataframe(table, hide_index=True, height=650, column_config={
        "market_rank": st.column_config.NumberColumn("趋势排名", pinned=True, format="%d"),
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
            st.metric("趋势排名", f"{int(row['market_rank'])} / {len(rankings)}", border=True)
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

with compare_tab:
    st.subheader("手动选择个股进行比较", anchor=False)
    st.caption("可从全部310只股票中选择最多8只，不受侧边栏子行业、标签和市值筛选影响。")
    stock_names = rankings.set_index("ts_code")["name"].to_dict()
    stock_options = rankings.sort_values("market_rank")["ts_code"].tolist()
    default_comparison = stock_options[:3]
    comparison_codes = st.multiselect(
        "比较股票",
        stock_options,
        default=default_comparison,
        format_func=lambda code: f"{stock_names[code]} · {code}",
        max_selections=8,
        placeholder="输入名称或代码搜索，最多选择8只",
        key="comparison_codes",
    )

    if not comparison_codes:
        st.info("请至少选择一只股票开始比较。", icon=":material/compare_arrows:")
    else:
        comparison = rankings[rankings["ts_code"].isin(comparison_codes)].sort_values("market_rank").copy()
        comparison_table = comparison[
            [
                "market_rank", "name", "ts_code", "healthcare_subindustry", "group", "signal_label",
                "momentum_score", "overheat_score", "valuation_score", "risk_score",
                "ret_5d", "ret_20d", "ret_60d", "ret_120d", "drawdown_60d",
                "latest_pe_ttm", "latest_pb", "market_cap_100m",
            ]
        ]
        with st.container(border=True):
            st.markdown("**核心指标对照**")
            st.dataframe(
                comparison_table,
                hide_index=True,
                column_config={
                    "market_rank": st.column_config.NumberColumn("趋势排名", pinned=True, format="%d"),
                    "name": st.column_config.TextColumn("股票", pinned=True),
                    "ts_code": "代码",
                    "healthcare_subindustry": "子行业",
                    "group": "趋势标签",
                    "signal_label": "研究信号",
                    "momentum_score": st.column_config.ProgressColumn("趋势分", min_value=0, max_value=100, format="%.1f"),
                    "overheat_score": st.column_config.ProgressColumn("过热分", min_value=0, max_value=100, format="%.1f"),
                    "valuation_score": st.column_config.ProgressColumn("估值分", min_value=0, max_value=100, format="%.1f"),
                    "risk_score": st.column_config.ProgressColumn("风险分", min_value=0, max_value=100, format="%.1f"),
                    "ret_5d": st.column_config.NumberColumn("5日", format="percent"),
                    "ret_20d": st.column_config.NumberColumn("20日", format="percent"),
                    "ret_60d": st.column_config.NumberColumn("60日", format="percent"),
                    "ret_120d": st.column_config.NumberColumn("120日", format="percent"),
                    "drawdown_60d": st.column_config.NumberColumn("距60日高点", format="percent"),
                    "latest_pe_ttm": st.column_config.NumberColumn("PE_TTM", format="%.1f"),
                    "latest_pb": st.column_config.NumberColumn("PB", format="%.2f"),
                    "market_cap_100m": st.column_config.NumberColumn("总市值(亿)", format="%.0f"),
                },
            )

        chart_left, chart_right = st.columns(2, gap="medium")
        with chart_left.container(border=True):
            st.markdown("**趋势与过热位置**")
            market_background = alt.Chart(rankings).mark_circle(size=35, color="#C8CDD2", opacity=0.35).encode(
                x=alt.X("momentum_score:Q", title="趋势分", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("overheat_score:Q", title="过热分", scale=alt.Scale(domain=[0, 100])),
            )
            selected_points = alt.Chart(comparison).mark_circle(size=180, stroke="white", strokeWidth=1.5).encode(
                x="momentum_score:Q",
                y="overheat_score:Q",
                color=alt.Color("name:N", title="股票"),
                tooltip=[
                    alt.Tooltip("name:N", title="股票"),
                    alt.Tooltip("market_rank:Q", title="趋势排名"),
                    alt.Tooltip("momentum_score:Q", title="趋势分", format=".1f"),
                    alt.Tooltip("overheat_score:Q", title="过热分", format=".1f"),
                    alt.Tooltip("signal_label:N", title="研究信号"),
                ],
            )
            selected_labels = alt.Chart(comparison).mark_text(dx=9, dy=-9, fontSize=11).encode(
                x="momentum_score:Q", y="overheat_score:Q", text="name:N", color=alt.Color("name:N", legend=None)
            )
            comparison_rules = alt.layer(
                alt.Chart(pd.DataFrame({"x": [70]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(x="x:Q"),
                alt.Chart(pd.DataFrame({"y": [90]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(y="y:Q"),
            )
            st.altair_chart(
                (market_background + selected_points + selected_labels + comparison_rules)
                .properties(height=390)
                .interactive()
            )

        with chart_right.container(border=True):
            st.markdown("**多周期收益对照**")
            return_comparison = comparison.melt(
                id_vars=["name"],
                value_vars=["ret_5d", "ret_20d", "ret_60d", "ret_120d"],
                var_name="period",
                value_name="return_value",
            )
            return_comparison["period"] = return_comparison["period"].map(
                {"ret_5d": "5日", "ret_20d": "20日", "ret_60d": "60日", "ret_120d": "120日"}
            )
            return_bars = alt.Chart(return_comparison).mark_bar().encode(
                x=alt.X("period:N", title=None, sort=["5日", "20日", "60日", "120日"]),
                y=alt.Y("return_value:Q", title="收益率", axis=alt.Axis(format="%")),
                xOffset="name:N",
                color=alt.Color("name:N", title="股票"),
                tooltip=[
                    alt.Tooltip("name:N", title="股票"),
                    alt.Tooltip("period:N", title="周期"),
                    alt.Tooltip("return_value:Q", title="收益率", format=".1%"),
                ],
            ).properties(height=390)
            st.altair_chart(return_bars)

        with st.container(border=True):
            comparison_horizon = st.segmented_control(
                "比较区间", ["60日", "120日", "250日"], default="120日", required=True, key="comparison_horizon"
            )
            comparison_history = normalized_history(
                history, comparison_codes, {"60日": 60, "120日": 120, "250日": 250}[comparison_horizon]
            )
            comparison_history["name"] = comparison_history["ts_code"].map(stock_names)
            comparison_line = alt.Chart(comparison_history).mark_line(strokeWidth=2.2).encode(
                x=alt.X("trade_date:T", title=None),
                y=alt.Y("normalized:Q", title="区间起点=100", scale=alt.Scale(zero=False)),
                color=alt.Color("name:N", title="股票"),
                tooltip=[
                    alt.Tooltip("trade_date:T", title="日期"),
                    alt.Tooltip("name:N", title="股票"),
                    alt.Tooltip("normalized:Q", title="指数", format=".1f"),
                ],
            ).properties(height=430).interactive()
            st.altair_chart(comparison_line)
            st.caption("所有股票按各自区间首个有效收盘价归一化为100，用于比较相对走势，不代表实际价格。")

with method_tab:
    st.subheader("评分方法与数据边界", anchor=False)
    st.markdown(
        """
        - **趋势强度**：5/20/60/120日收益的全市场与子行业内排名，叠加均线和距高点确认；20日、60日窗口权重最高。
        - **估值分**：PE_TTM和PB只在所属子行业内比较；正PE权重60%，正PB权重40%；负PE或缺失PE不被当作便宜，估值分会因有效字段不足而降权。
        - **研究信号**：强趋势低过热、强趋势高过热、估值便宜待确认、弱趋势/数据不足。它们是研究优先级，不是买卖评级。
        - **风险分**：追高风险、20日年化波动率和价格数据滞后度的组合；分数越高，风险越高。
        - **A/B/C历史表现**：过去三年非重叠5/20/120日回测中，A组均未表现出更高的平均未来收益，因此分组只描述当前趋势确认程度，不构成收益评级。
        - **质量分暂未启用**：当前快照没有ROE、营收增速、扣非利润增速和结构化新闻字段，因此看板不会假装拥有这些信息。
        """
    )
    st.warning(f"价格截至 {meta['as_of_date']}；估值字段截至 {meta.get('valuation_as_of_date', '未知')}，两者可能存在时点差异。看板用于研究和监控，不构成投资建议。", icon=":material/warning:")
