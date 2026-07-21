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
RISK_HORIZON = 20
OVERHEAT_THRESHOLD = 90

st.set_page_config(page_title="A股医疗趋势看板", page_icon=":material/query_stats:", layout="wide")


@st.cache_data(show_spinner="正在载入研究快照…")
def load_snapshot():
    rankings = pd.read_csv(DATA_DIR / "momentum_snapshot.csv", parse_dates=["price_date"])
    history = pd.read_csv(DATA_DIR / "price_history.csv.gz", parse_dates=["trade_date"])
    two_dimension_backtest = pd.read_csv(DATA_DIR / "two_dimension_backtest.csv")
    group_backtest_metadata = json.loads(
        (DATA_DIR / "group_backtest_metadata.json").read_text(encoding="utf-8")
    )
    risk_oos = pd.read_csv(DATA_DIR / "survivorship_free_risk_model_summary.csv")
    risk_oos_yearly = pd.read_csv(DATA_DIR / "survivorship_free_risk_model_yearly.csv")
    model_scores = pd.read_csv(DATA_DIR / "model_current_scores.csv")
    model_scores["model_training_end"] = pd.to_datetime(
        model_scores["model_training_end"], format="mixed"
    )
    production_risk_model = json.loads(
        (DATA_DIR / "production_risk_model.json").read_text(encoding="utf-8")
    )
    risk_model_metadata = json.loads(
        (DATA_DIR / "survivorship_free_risk_model_metadata.json").read_text(encoding="utf-8")
    )
    metadata = json.loads((DATA_DIR / "metadata.json").read_text(encoding="utf-8"))
    return (
        rankings,
        history,
        two_dimension_backtest,
        group_backtest_metadata,
        risk_oos,
        risk_oos_yearly,
        model_scores,
        production_risk_model,
        risk_model_metadata,
        metadata,
    )


def pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.1%}"


def normalized_history(history: pd.DataFrame, codes: list[str], sessions: int) -> pd.DataFrame:
    selected = history[history["ts_code"].isin(codes)].copy()
    selected = (
        selected.sort_values(["ts_code", "trade_date"])
        .groupby("ts_code", as_index=False)
        .tail(sessions)
    )
    selected["normalized"] = selected.groupby("ts_code")["close_qfq"].transform(
        lambda series: series / series.iloc[0] * 100
    )
    return selected


def apply_simple_labels(rankings: pd.DataFrame, model_scores: pd.DataFrame) -> pd.DataFrame:
    """Use the official 20-day drawdown model as the dashboard's only risk signal."""
    risk = model_scores.loc[
        model_scores["horizon_sessions"] == RISK_HORIZON,
        ["ts_code", "drawdown_risk_score", "risk_model_version", "model_training_end"],
    ].copy()
    if risk["ts_code"].duplicated().any():
        raise ValueError("20-day drawdown model contains duplicate stock codes")

    result = rankings.drop(
        columns=["group", "signal_label", "overheat_score"], errors="ignore"
    ).merge(risk, on="ts_code", how="left", validate="one_to_one")
    if result["drawdown_risk_score"].isna().any():
        missing = result.loc[result["drawdown_risk_score"].isna(), "ts_code"].tolist()
        raise ValueError(f"20-day drawdown risk score missing for {len(missing)} stocks: {missing[:5]}")

    result["overheat_score"] = result["drawdown_risk_score"]
    strong = result["momentum_score"] >= 70
    medium = result["momentum_score"] >= 40
    overheated = result["overheat_score"] >= OVERHEAT_THRESHOLD
    result["group"] = np.select(
        [strong & ~overheated, medium],
        ["A", "B"],
        default="C",
    )
    result["signal_label"] = np.select(
        [strong & ~overheated, strong & overheated, medium],
        ["强趋势/风险可控", "强趋势/过热", "中等趋势"],
        default="弱趋势",
    )
    result["trend_bucket"] = pd.cut(
        result["momentum_score"],
        [-np.inf, 40, 70, np.inf],
        labels=["弱趋势", "中趋势", "强趋势"],
        right=False,
    ).astype("string")
    result["risk_bucket"] = pd.cut(
        result["overheat_score"],
        [-np.inf, 30, 70, np.inf],
        labels=["低风险", "中风险", "高风险"],
        right=False,
    ).astype("string")
    result["two_dimension_label"] = result["trend_bucket"] + " + " + result["risk_bucket"]
    result["overheat_state"] = np.where(overheated, "过热", "未过热")
    return result


def set_all_industries() -> None:
    st.session_state["selected_industries"] = list(ALL_INDUSTRIES)


def clear_industries() -> None:
    st.session_state["selected_industries"] = []


def apply_preset() -> None:
    st.session_state["selected_industries"] = list(
        INDUSTRY_PRESETS[st.session_state["industry_preset"]]
    )


def apply_industry_batch() -> None:
    current = set(st.session_state.get("selected_industries", []))
    additions = set(st.session_state.get("industry_add", []))
    removals = set(st.session_state.get("industry_remove", []))
    st.session_state["selected_industries"] = sorted((current | additions) - removals)


(
    raw_rankings,
    history,
    two_dimension_backtest,
    group_backtest_meta,
    risk_oos,
    risk_oos_yearly,
    model_scores,
    production_risk_model,
    risk_model_meta,
    meta,
) = load_snapshot()
rankings = apply_simple_labels(raw_rankings, model_scores)

ALL_INDUSTRIES = sorted(rankings["healthcare_subindustry"].dropna().unique().tolist())
industry_summary = (
    rankings.groupby("healthcare_subindustry", as_index=False)
    .agg(
        stock_count=("ts_code", "count"),
        median_momentum=("momentum_score", "median"),
        median_overheat=("overheat_score", "median"),
        high_risk_count=("risk_bucket", lambda values: (values == "高风险").sum()),
        strong_trend_count=("trend_bucket", lambda values: (values == "强趋势").sum()),
    )
)
top_industries = (
    industry_summary.nlargest(7, "median_momentum")["healthcare_subindustry"].tolist()
)
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
        add_options = [industry for industry in ALL_INDUSTRIES if industry not in current]
        remove_options = sorted(current)
        st.multiselect("批量加入", add_options, key="industry_add", placeholder="可多选")
        st.multiselect("批量删除", remove_options, key="industry_remove", placeholder="可多选")
        st.form_submit_button("应用批量修改", on_click=apply_industry_batch, icon=":material/tune:")

    selected_trends = st.pills(
        "趋势档",
        ["强趋势", "中趋势", "弱趋势"],
        default=["强趋势", "中趋势", "弱趋势"],
        key="selected_trends",
        selection_mode="multi",
    )
    selected_risks = st.pills(
        "风险档",
        ["低风险", "中风险", "高风险"],
        default=["低风险", "中风险", "高风险"],
        key="selected_risks",
        selection_mode="multi",
    )
    market_cap_max = int(np.ceil(rankings["market_cap_100m"].max() / 100) * 100)
    market_cap_range = st.slider("总市值（亿元）", 0, market_cap_max, (0, market_cap_max), 10)
    search = st.text_input("搜索股票", placeholder="输入名称或代码")
    st.caption(
        f"行情截止 {meta['as_of_date']} · 趋势口径 固定公式100分制 · "
        f"风险口径 {RISK_HORIZON}日最大不利波动（MAE）"
    )

filtered = rankings[
    rankings["healthcare_subindustry"].isin(st.session_state.get("selected_industries", []))
    & rankings["trend_bucket"].isin(selected_trends or [])
    & rankings["risk_bucket"].isin(selected_risks or [])
    & rankings["market_cap_100m"].fillna(0).between(*market_cap_range)
].copy()
if search:
    term = search.strip().lower()
    filtered = filtered[
        filtered["name"].fillna("").str.lower().str.contains(term, regex=False)
        | filtered["ts_code"].str.lower().str.contains(term, regex=False)
    ]

st.title(":material/query_stats: A股医疗趋势看板")
st.caption(
    f"覆盖 {meta['stock_count']} 只股票、{meta['subindustry_count']} 个子行业。"
    "趋势分使用理论满分100分的固定公式；"
    "风险分表示未来20日最大不利波动的相对排名。"
)

with st.container(horizontal=True):
    st.metric("当前样本", f"{len(filtered)} 只", border=True)
    st.metric("强趋势", f"{(filtered['trend_bucket'] == '强趋势').sum()} 只", border=True)
    st.metric("低风险", f"{(filtered['risk_bucket'] == '低风险').sum()} 只", border=True)
    st.metric("趋势分中位数", f"{filtered['momentum_score'].median():.1f}", border=True)
    st.metric("风险分中位数", f"{filtered['overheat_score'].median():.1f}", border=True)

overview_tab, backtest_tab, method_tab, stock_tab, compare_tab = st.tabs(
    ["市场状态", "回测结果", "评分方法", "个股拆解", "个股比较"]
)

with overview_tab:
    st.subheader("趋势与回撤风险", anchor=False)
    left, right = st.columns([1, 2], gap="medium")
    with left.container(border=True):
        st.markdown("**强趋势 + 低风险**")
        candidates = filtered[
            (filtered["trend_bucket"] == "强趋势")
            & (filtered["risk_bucket"] == "低风险")
        ].nsmallest(12, "market_rank")
        st.dataframe(
            candidates[
                ["market_rank", "name", "healthcare_subindustry", "momentum_score", "overheat_score"]
            ],
            hide_index=True,
            height=410,
            column_config={
                "market_rank": "排名",
                "name": st.column_config.TextColumn("股票", pinned=True),
                "healthcare_subindustry": "子行业",
                "momentum_score": st.column_config.ProgressColumn("趋势分", min_value=0, max_value=100, format="%.1f"),
                "overheat_score": st.column_config.ProgressColumn("风险分", min_value=0, max_value=100, format="%.1f"),
            },
        )
    with right.container(border=True):
        scatter = alt.Chart(filtered).mark_circle(opacity=0.8, stroke="white", strokeWidth=0.5).encode(
            x=alt.X("momentum_score:Q", title="趋势分", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("overheat_score:Q", title="20日MAE风险分", scale=alt.Scale(domain=[0, 100])),
            size=alt.Size("market_cap_100m:Q", title="总市值（亿元）", scale=alt.Scale(range=[35, 850])),
            color=alt.Color(
                "risk_bucket:N",
                title="风险档",
                scale=alt.Scale(domain=["低风险", "中风险", "高风险"], range=["#2E7D5B", "#D89B2B", "#C8423B"]),
            ),
            tooltip=[
                alt.Tooltip("name:N", title="股票"),
                alt.Tooltip("ts_code:N", title="代码"),
                alt.Tooltip("healthcare_subindustry:N", title="子行业"),
                alt.Tooltip("two_dimension_label:N", title="二维标签"),
                alt.Tooltip("momentum_score:Q", title="趋势分", format=".1f"),
                alt.Tooltip("overheat_score:Q", title="风险分", format=".1f"),
            ],
        )
        rules = alt.layer(
            alt.Chart(pd.DataFrame({"x": [40]})).mark_rule(color="#AAB2B9", strokeDash=[3, 3]).encode(x="x:Q"),
            alt.Chart(pd.DataFrame({"x": [70]})).mark_rule(color="#4F6D7A", strokeDash=[4, 4]).encode(x="x:Q"),
            alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="#2E7D5B", strokeDash=[3, 3]).encode(y="y:Q"),
            alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(y="y:Q"),
        )
        st.altair_chart((scatter + rules).properties(height=410).interactive())
        st.caption("二维分档：趋势40/70为分界，风险30/70为分界；分数越高表示预测MAE风险越高。")

    with st.container(border=True):
        st.markdown("**当前二维分布**")
        current_matrix = (
            filtered.groupby(["trend_bucket", "risk_bucket"], observed=True)
            .size()
            .unstack(fill_value=0)
            .reindex(index=["强趋势", "中趋势", "弱趋势"], columns=["低风险", "中风险", "高风险"], fill_value=0)
        )
        current_matrix.index.name = "趋势档"
        current_matrix.columns.name = "风险档"
        st.dataframe(current_matrix)

    with st.container(border=True):
        st.markdown("**子行业趋势**")
        industry_view = industry_summary[
            industry_summary["healthcare_subindustry"].isin(
                st.session_state.get("selected_industries", [])
            )
        ].copy()
        bars = alt.Chart(industry_view).mark_bar(cornerRadiusEnd=3, color="#587A95").encode(
            x=alt.X("median_momentum:Q", title="趋势分中位数", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("healthcare_subindustry:N", title=None, sort="-x"),
            tooltip=[
                alt.Tooltip("healthcare_subindustry:N", title="子行业"),
                alt.Tooltip("stock_count:Q", title="股票数"),
                alt.Tooltip("median_momentum:Q", title="趋势分中位数", format=".1f"),
                alt.Tooltip("median_overheat:Q", title="风险分中位数", format=".1f"),
                alt.Tooltip("strong_trend_count:Q", title="强趋势数量"),
                alt.Tooltip("high_risk_count:Q", title="高风险数量"),
            ],
        ).properties(height=max(300, 22 * len(industry_view)))
        st.altair_chart(bars)

    with st.container(border=True):
        st.markdown("**股票清单**")
        market_table = filtered[
            [
                "market_rank", "name", "ts_code", "healthcare_subindustry",
                "trend_bucket", "risk_bucket", "momentum_score", "overheat_score",
                "ret_5d", "ret_20d", "ret_60d", "ret_120d", "market_cap_100m",
            ]
        ].copy()
        st.dataframe(
            market_table,
            hide_index=True,
            height=560,
            column_config={
                "market_rank": st.column_config.NumberColumn("趋势排名", pinned=True, format="%d"),
                "name": st.column_config.TextColumn("股票", pinned=True),
                "ts_code": "代码",
                "healthcare_subindustry": "子行业",
                "trend_bucket": "趋势档",
                "risk_bucket": "风险档",
                "momentum_score": st.column_config.ProgressColumn("趋势分", min_value=0, max_value=100, format="%.1f"),
                "overheat_score": st.column_config.ProgressColumn("风险分", min_value=0, max_value=100, format="%.1f"),
                "ret_5d": st.column_config.NumberColumn("5日", format="percent"),
                "ret_20d": st.column_config.NumberColumn("20日", format="percent"),
                "ret_60d": st.column_config.NumberColumn("60日", format="percent"),
                "ret_120d": st.column_config.NumberColumn("120日", format="percent"),
                "market_cap_100m": st.column_config.NumberColumn("总市值(亿)", format="%.0f"),
            },
        )
        st.download_button(
            "下载当前筛选结果",
            market_table.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"a_share_healthcare_trend_risk_{meta['as_of_date']}.csv",
            mime="text/csv",
            icon=":material/download:",
        )

with backtest_tab:
    st.subheader("趋势 × 风险二维回测", anchor=False)
    matrix_horizon_label = st.segmented_control(
        "二维矩阵周期",
        ["5日", "20日"],
        default="5日",
        required=True,
        key="two_dimension_horizon",
    )
    matrix_horizon = int(matrix_horizon_label.removesuffix("日"))
    matrix_data = two_dimension_backtest[
        two_dimension_backtest["horizon_sessions"] == matrix_horizon
    ].copy()
    trend_order = ["强趋势", "中趋势", "弱趋势"]
    risk_order = ["低风险", "中风险", "高风险"]

    return_matrix = matrix_data.pivot(
        index="trend_bucket", columns="risk_bucket", values="average_forward_return"
    ).reindex(index=trend_order, columns=risk_order)
    drawdown_matrix = matrix_data.pivot(
        index="trend_bucket", columns="risk_bucket", values="average_forward_drawdown"
    ).reindex(index=trend_order, columns=risk_order)
    count_matrix = matrix_data.pivot(
        index="trend_bucket", columns="risk_bucket", values="average_stock_count"
    ).reindex(index=trend_order, columns=risk_order)
    period_matrix = matrix_data.pivot(
        index="trend_bucket", columns="risk_bucket", values="period_count"
    ).reindex(index=trend_order, columns=risk_order)
    for matrix in [return_matrix, drawdown_matrix, count_matrix, period_matrix]:
        matrix.index.name = "趋势档"
        matrix.columns.name = "风险档"

    st.caption(
        "趋势档：强≥70、中40–70、弱<40；风险档：低<30、中30–70、高≥70。"
        "每格先在每个调仓日对股票等权，再对调仓期等权平均。"
    )
    matrix_left, matrix_right = st.columns(2, gap="medium")
    with matrix_left.container(border=True):
        st.markdown(f"**未来{matrix_horizon}日平均收益**")
        st.dataframe(
            return_matrix,
            column_config={
                bucket: st.column_config.NumberColumn(bucket, format="percent")
                for bucket in risk_order
            },
        )
    with matrix_right.container(border=True):
        st.markdown(f"**未来{matrix_horizon}日平均最大不利波动**")
        st.dataframe(
            drawdown_matrix,
            column_config={
                bucket: st.column_config.NumberColumn(bucket, format="percent")
                for bucket in risk_order
            },
        )

    support_left, support_right = st.columns(2, gap="medium")
    with support_left.container(border=True):
        st.markdown("**每格平均股票数**")
        st.dataframe(
            count_matrix,
            column_config={
                bucket: st.column_config.NumberColumn(bucket, format="%.1f")
                for bucket in risk_order
            },
        )
    with support_right.container(border=True):
        st.markdown("**有效调仓期数**")
        st.dataframe(
            period_matrix,
            column_config={
                bucket: st.column_config.NumberColumn(bucket, format="%d")
                for bucket in risk_order
            },
        )

    strong_low = matrix_data[
        (matrix_data["trend_bucket"] == "强趋势")
        & (matrix_data["risk_bucket"] == "低风险")
    ].iloc[0]
    st.info(
        f"强趋势+低风险的未来{matrix_horizon}日平均收益为"
        f"{strong_low['average_forward_return']:.2%}，平均最大不利波动为"
        f"{strong_low['average_forward_drawdown']:.2%}。但该格平均只有"
        f"{strong_low['average_stock_count']:.1f}只股票，且只在"
        f"{int(strong_low['period_count'])}个调仓期出现，收益均值容易受少数股票影响。"
    )
    with st.expander("回测口径与局限"):
        st.markdown(
            f"""
            - 二维规则：趋势强≥70、中40–70、弱<40；风险低<30、中30–70、高≥70。
            - 风险模型：{group_backtest_meta['risk_training_rule']}，不使用未来数据形成历史分组。
            - 成交口径：{group_backtest_meta['execution']}；{group_backtest_meta['weighting']}。
            - 未计交易成本、涨跌停和冲击成本；{group_backtest_meta['universe_note']}
            - 5日矩阵有146个非重叠调仓期，20日矩阵有37个非重叠调仓期。某些单元格在部分日期为空，因此同时展示有效期数。
            """
        )

with stock_tab:
    st.subheader("个股拆解", anchor=False)
    options = filtered.sort_values("market_rank").apply(
        lambda row: f"{row['name']} · {row['ts_code']}", axis=1
    ).tolist()
    if not options:
        st.info("当前筛选条件下没有股票。")
    else:
        selected_label = st.selectbox("选择股票", options)
        selected_code = selected_label.rsplit(" · ", 1)[1]
        row = rankings.loc[rankings["ts_code"] == selected_code].iloc[0]
        with st.container(horizontal=True):
            st.metric("趋势排名", f"{int(row['market_rank'])} / {len(rankings)}", border=True)
            st.metric("二维标签", row["two_dimension_label"], border=True)
            st.metric("趋势分", f"{row['momentum_score']:.1f}", border=True)
            st.metric("风险分", f"{row['overheat_score']:.1f}", border=True)

        detail_left, detail_right = st.columns(2, gap="medium")
        with detail_left.container(border=True):
            st.markdown("**趋势拆解**")
            st.write(
                f"5日 {pct(row['ret_5d'])} · 20日 {pct(row['ret_20d'])} · "
                f"60日 {pct(row['ret_60d'])} · 120日 {pct(row['ret_120d'])}"
            )
            st.write(
                f"距MA20 {pct(row['ma20_gap'])} · 距MA60 {pct(row['ma60_gap'])} · "
                f"距60日高点 {pct(row['drawdown_60d'])}"
            )
        with detail_right.container(border=True):
            st.markdown("**MAE风险拆解**")
            st.write(
                f"{RISK_HORIZON}日回撤模型分：{row['overheat_score']:.1f} · "
                f"风险档：{row['risk_bucket']} · 模型：{row['risk_model_version']}"
            )
            st.write(
                f"子行业：{row['healthcare_subindustry']} · "
                f"价格日期：{row['price_date'].date()} · "
                f"模型训练截止：{row['model_training_end'].date()}"
            )

        horizon = st.segmented_control(
            "走势区间", ["60日", "120日", "250日"], default="120日", required=True
        )
        selected_history = normalized_history(
            history, [selected_code], {"60日": 60, "120日": 120, "250日": 250}[horizon]
        )
        line = alt.Chart(selected_history).mark_line(color="#D94B4B", strokeWidth=2.5).encode(
            x=alt.X("trade_date:T", title=None),
            y=alt.Y("normalized:Q", title="区间起点=100", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("trade_date:T", title="日期"),
                alt.Tooltip("normalized:Q", title="指数", format=".1f"),
            ],
        ).properties(height=390).interactive()
        st.altair_chart(line)

with compare_tab:
    st.subheader("手动选择个股进行比较", anchor=False)
    st.caption("可从全310只股票中选择最多8只，不受侧边栏筛选影响。")
    stock_names = rankings.set_index("ts_code")["name"].to_dict()
    stock_options = rankings.sort_values("market_rank")["ts_code"].tolist()
    comparison_codes = st.multiselect(
        "比较股票",
        stock_options,
        default=stock_options[:3],
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
                "market_rank", "name", "ts_code", "healthcare_subindustry", "trend_bucket", "risk_bucket",
                "momentum_score", "overheat_score", "ret_5d", "ret_20d", "ret_60d",
                "ret_120d", "market_cap_100m",
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
                    "trend_bucket": "趋势档",
                    "risk_bucket": "风险档",
                    "momentum_score": st.column_config.ProgressColumn("趋势分", min_value=0, max_value=100, format="%.1f"),
                    "overheat_score": st.column_config.ProgressColumn("风险分", min_value=0, max_value=100, format="%.1f"),
                    "ret_5d": st.column_config.NumberColumn("5日", format="percent"),
                    "ret_20d": st.column_config.NumberColumn("20日", format="percent"),
                    "ret_60d": st.column_config.NumberColumn("60日", format="percent"),
                    "ret_120d": st.column_config.NumberColumn("120日", format="percent"),
                    "market_cap_100m": st.column_config.NumberColumn("总市值(亿)", format="%.0f"),
                },
            )

        chart_left, chart_right = st.columns(2, gap="medium")
        with chart_left.container(border=True):
            st.markdown("**趋势与风险位置**")
            background = alt.Chart(rankings).mark_circle(size=35, color="#C8CDD2", opacity=0.35).encode(
                x=alt.X("momentum_score:Q", title="趋势分", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("overheat_score:Q", title="MAE风险分", scale=alt.Scale(domain=[0, 100])),
            )
            points = alt.Chart(comparison).mark_circle(size=180, stroke="white", strokeWidth=1.5).encode(
                x="momentum_score:Q",
                y="overheat_score:Q",
                color=alt.Color("name:N", title="股票"),
                tooltip=[
                    alt.Tooltip("name:N", title="股票"),
                    alt.Tooltip("market_rank:Q", title="趋势排名"),
                    alt.Tooltip("momentum_score:Q", title="趋势分", format=".1f"),
                    alt.Tooltip("overheat_score:Q", title="风险分", format=".1f"),
                    alt.Tooltip("two_dimension_label:N", title="二维标签"),
                ],
            )
            labels = alt.Chart(comparison).mark_text(dx=9, dy=-9, fontSize=11).encode(
                x="momentum_score:Q", y="overheat_score:Q", text="name:N",
                color=alt.Color("name:N", legend=None),
            )
            rules = alt.layer(
                alt.Chart(pd.DataFrame({"x": [40]})).mark_rule(color="#AAB2B9", strokeDash=[3, 3]).encode(x="x:Q"),
                alt.Chart(pd.DataFrame({"x": [70]})).mark_rule(color="#4F6D7A", strokeDash=[4, 4]).encode(x="x:Q"),
                alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="#2E7D5B", strokeDash=[3, 3]).encode(y="y:Q"),
                alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="#C8423B", strokeDash=[4, 4]).encode(y="y:Q"),
            )
            st.altair_chart((background + points + labels + rules).properties(height=390).interactive())

        with chart_right.container(border=True):
            st.markdown("**多周期收益对照**")
            returns = comparison.melt(
                id_vars=["name"],
                value_vars=["ret_5d", "ret_20d", "ret_60d", "ret_120d"],
                var_name="period",
                value_name="return_value",
            )
            returns["period"] = returns["period"].map(
                {"ret_5d": "5日", "ret_20d": "20日", "ret_60d": "60日", "ret_120d": "120日"}
            )
            return_bars = alt.Chart(returns).mark_bar().encode(
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
                "比较区间", ["60日", "120日", "250日"], default="120日", required=True,
                key="comparison_horizon",
            )
            comparison_history = normalized_history(
                history,
                comparison_codes,
                {"60日": 60, "120日": 120, "250日": 250}[comparison_horizon],
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
            st.caption("所有股票按各自区间首个有效收盘价归一化为100。")

with method_tab:
    st.subheader("评分方法", anchor=False)
    with st.container(horizontal=True):
        st.metric("趋势分理论满分", "100", border=True)
        st.metric("收益窗口合计", "90分", border=True)
        st.metric("趋势确认合计", "10分", border=True)
        st.metric("强趋势门槛", "70分", border=True)
    trend_col, risk_col = st.columns(2, gap="medium")
    with trend_col.container(border=True):
        st.markdown("**趋势分：描述过去价格强弱**")
        st.markdown(
            """
            趋势分是固定公式的0–100分，理论满分为100，不是未来收益概率。收益率先分别计算全310只股票和所属子行业内的百分位，再按固定权重合成：

            | 因子 | 权重 |
            |---|---:|
            | 5日收益率 | 10% |
            | 20日收益率 | 30% |
            | 60日收益率 | 35% |
            | 120日收益率 | 15% |
            | 相对MA20位置 | 5% |
            | 距60日高点位置 | 5% |

            四个收益窗口合计贡献90分：全股票池排名合计65分，子行业内排名合计25分；均线与高点确认合计10分。该公式不会再按当日分数分布做二次映射。
            """
        )
        st.code(
            "趋势分 = 65 x 全市场收益排名组合\n"
            "       + 25 x 子行业收益排名组合\n"
            "       +  5 x MA20位置得分\n"
            "       +  5 x 60日高点位置得分",
            language=None,
        )
        st.write("趋势分档：强趋势 ≥70 · 中趋势 40–70 · 弱趋势 <40")

    with risk_col.container(border=True):
        st.markdown("**风险分：动态历史股票池7因子模型**")
        st.markdown(
            "风险分是7因子Ridge模型预测值在当前310只股票中的横截面百分位；"
            "分数越高，未来20日MAE风险相对越高。MAE=max(0, -持有期内最低累计收益)；"
            "若价格从未跌破建仓价，MAE记为0。"
        )
        risk_factor_table = pd.DataFrame(
            {
                "因子组": ["波动"] * 3 + ["价格事件"] * 2 + ["市场与资金"] * 2,
                "具体因子": [
                    "20日日内振幅/ATR",
                    "60日波动率",
                    "60日下行波动率",
                    "20日最大单日涨幅",
                    "跳空与极端下跌",
                    "60日医疗板块Beta",
                    "拥挤度季度变化",
                ],
            }
        )
        st.dataframe(risk_factor_table, hide_index=True, height=285)
        st.write("风险分档：低风险 <30 · 中风险 30–70 · 高风险 ≥70 · 极端过热 ≥90")

    st.markdown("### 回撤模型验证")
    selected_result = risk_oos.iloc[0]
    with st.container(horizontal=True):
        st.metric("当前模型", production_risk_model["model_version"], border=True)
        st.metric("样本外Rank IC", f"{selected_result['mean_rank_ic']:.3f}", border=True)
        st.metric("高-低风险MAE差", pct(selected_result["top_bottom_spread"]), border=True)
        st.metric("尾部风险召回率", pct(selected_result["top_decile_recall"]), border=True)

    validation_left, validation_right = st.columns(2, gap="medium")
    with validation_left.container(border=True):
        st.markdown("**无幸存者偏差样本外结果**")
        st.dataframe(
            risk_oos[["model", "mean_rank_ic", "top_bottom_spread", "top_decile_recall", "rebalance_count"]],
            hide_index=True,
            column_config={
                "model": "模型",
                "mean_rank_ic": st.column_config.NumberColumn("样本外Rank IC", format="%.3f"),
                "top_bottom_spread": st.column_config.NumberColumn("高-低风险MAE差", format="percent"),
                "top_decile_recall": st.column_config.NumberColumn("尾部召回率", format="percent"),
                "rebalance_count": "独立调仓期",
            },
        )
    with validation_right.container(border=True):
        st.markdown("**逐年样本外Rank IC**")
        yearly_chart = alt.Chart(risk_oos_yearly).mark_bar(color="#C8423B").encode(
            x=alt.X("test_year:O", title="测试年份"),
            y=alt.Y("mean_rank_ic:Q", title="平均Rank IC"),
            tooltip=[
                alt.Tooltip("test_year:O", title="年份"),
                alt.Tooltip("mean_rank_ic:Q", title="Rank IC", format=".3f"),
            ],
        ).properties(height=300)
        st.altair_chart(yearly_chart)

    with st.expander("训练、中性化与数据边界"):
        st.markdown(
            f"""
            - 历史股票池：{risk_model_meta['universe_definition']}。
            - 成分规则：{risk_model_meta['membership_rule']}。
            - 因子中性化：调仓日有效的申万二级行业哑变量 + 对数总市值。
            - 退市处理：{risk_model_meta['delisting_treatment']}。
            - 历史回测每个建仓日只使用当时已完成20日持有期的样本重训，不使用未来目标。
            - 当前模型训练截止：{rankings['model_training_end'].max().date()}。
            - 当前展示仍为310只广义医疗股票，其中{production_risk_model['theme_only_extrapolation_count']}只仅来自医疗主题指数，属于模型外推。
            - 2019–2026年已参与研发；真正前瞻样本从2026-07-20之后的预测开始累计。
            """
        )
    st.info(
        "趋势分和风险分是两个独立维度：趋势分用于排研究优先级，风险分用于评估回撤与仓位，不应合并解释为买入概率。"
    )
    st.warning(
        f"价格截至 {meta['as_of_date']}。看板用于研究和监控，不构成投资建议。",
        icon=":material/warning:",
    )
