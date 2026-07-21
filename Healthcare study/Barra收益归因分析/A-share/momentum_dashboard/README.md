# A股医疗动量看板

面向公开部署的 Streamlit 应用，覆盖 `Full version/universe` 中的310只A股医疗相关股票。

## 本地运行

```bash
streamlit run streamlit_app.py
```

## 更新数据快照

在 `momentum_dashboard` 目录运行：

```bash
export TUSHARE_TOKEN="your-token"
python update_prices.py --end-date YYYYMMDD
python build_snapshot.py
```

`update_prices.py` 按交易日批量补充日线与复权因子，并重建前复权宽表；`build_snapshot.py` 随后读取相邻的 `../Full version/universe` 数据，生成部署所需的轻量文件：

- `data/momentum_snapshot.csv`
- `data/subindustry_snapshot.csv`
- `data/price_history.csv.gz`

应用运行时不会调用 Tushare，也不需要任何密钥。先用原有数据流程更新股票池和前复权行情，再重新运行构建脚本即可更新公开看板。

重新训练无幸存者偏差的20日风险模型时运行：

```bash
python test_survivorship_free_risk_model.py --refresh-membership
```

该流程使用调仓日有效的申万医药生物历史成员，依据 `in_date/out_date` 动态纳入退市及被剔除股票，生成7因子Ridge模型、310只展示股票的当前风险分、样本外验证结果和轻量压缩训练面板。逐股票Tushare缓存仅用于本地重建，不参与云端部署。

随后重新计算过去三年的A/B/C分组和趋势×风险矩阵：

```bash
python backtest_groups.py
```

该脚本生成：

- `data/group_backtest_summary.csv`
- `data/group_backtest_yearly.csv`
- `data/group_backtest_metadata.json`

风险模型在每个历史建仓日仅使用当时已经完成20日持有期的动态申万历史样本滚动训练；收益与分组展示仍基于当前310只股票。分别按5、20和120个交易日的非重叠周期调仓并持有，组内等权。

运行单因子检验、十分位收益、中性化和滚动样本外模型：

```bash
python factor_research.py
```

该流程使用历史动态总市值、PE_TTM、PB和换手率；覆盖5/20/60/120日。收益模型与回撤模型分开训练，每个测试年度只使用此前已经结束持有期的数据。收益因子剔除子行业、市值和20日波动率影响，风险因子剔除子行业和市值影响。

`factor_research.py` 仍保留为候选因子研究流程。若 `data/production_risk_model.json` 存在，它不会覆盖正式20日风险模型；5/60/120日研究分仍沿用原选择逻辑。

## Streamlit Community Cloud

1. 将本目录连同 `data/` 提交到公开 Git 仓库。
2. 在 Streamlit Community Cloud 选择仓库。
3. Main file path 指向 `Healthcare study/Barra收益归因分析/A-share/momentum_dashboard/streamlit_app.py`。
4. 部署即可；无需配置 Secrets。

## 看板判断与分组

看板只保留两个判断维度：趋势分，以及正式20日回撤风险模型产生的风险分。风险模型目标为未来20日最大不利波动（MAE）：`max(0, -min(未来持有期收益路径))`。价格在持有期从未跌破建仓价时MAE记为0。风险分是MAE预测值在310只股票中的横截面百分位排名，分数越高表示相对风险越高。

当前正式风险模型为动态申万历史股票池训练的7因子Ridge：20日日内振幅/ATR、60日波动率、60日下行波动率、20日最大单日涨幅、跳空与极端下跌、60日医疗板块Beta、拥挤度季度变化。2023年起20日年度扩展窗口样本外Rank IC为0.318，42个非重叠调仓期全部为正。当前展示仍为310只广义医疗股票，其中18只主题指数独有股票属于模型外推。

主看板固定为5个页签：市场状态、回测结果、评分方法、个股拆解和个股比较。市场状态包含完整股票清单与下载；回测结果使用趋势三档与风险三档的二维矩阵；评分方法分开展示趋势因子权重、回撤风险因子和样本外验证。

- A：趋势分不低于70，且过热分低于90。
- B：趋势分不低于40，但不满足A组；强趋势但过热的股票也归入B组。
- C：趋势分低于40。

旧估值分、旧过热分、旧综合风险分、研究综合分和收益模型分不再用于看板判断与展示。旧A/B/C回测使用历史旧口径，与当前新分组不可混用，因此不再在主看板展示。看板用于研究和监控，不构成投资建议。

## 新分组回测

`backtest_groups.py` 已改为重建当前新口径。每个历史建仓日使用当时价格重算趋势分，并且只使用该日前已经完成20日持有期的动态申万历史样本滚动重训7因子Ridge模型，避免用今天的模型回填历史。过热分在当日310只展示股票中按风险预测值转成百分位。

回测生成：

- `data/group_backtest_summary.csv`：5/20/120日各组收益、超额收益、回撤、组规模和复利统计。
- `data/group_backtest_yearly.csv`：按建仓年份拆分的表现。
- `data/group_backtest_spreads.csv`：A-B、A-C和B-C的配对收益差及bootstrap 95%置信区间。
- `data/group_backtest_detail.csv.gz`：历史股票级分组与未来表现明细。
- `data/two_dimension_backtest.csv`：趋势三档（强≥70、中40–70、弱<40）与风险三档（低<30、中30–70、高≥70）交叉后的5/20/120日平均收益、平均MAE（以非正收益形式展示）、平均股票数和有效调仓期数。

看板用于研究和监控，不构成投资建议。
