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

重新计算过去三年的A/B/C分组回测时运行：

```bash
python backtest_groups.py
```

该脚本生成：

- `data/group_backtest_summary.csv`
- `data/group_backtest_yearly.csv`
- `data/group_backtest_metadata.json`

回测使用当前310只股票的历史行情，分别按5、20和120个交易日的非重叠周期调仓并持有，组内等权。日常行情更新无需重复运行，只有在回测区间或A/B/C规则变化时才需要重跑。

运行单因子检验、十分位收益、中性化和滚动样本外模型：

```bash
python factor_research.py
```

该流程使用历史动态总市值、PE_TTM、PB和换手率；覆盖5/20/60/120日。收益模型与回撤模型分开训练，每个测试年度只使用此前已经结束持有期的数据。收益因子剔除子行业、市值和20日波动率影响，风险因子剔除子行业和市值影响。

回撤研究同时测试60日下行波动率、60日残差波动率、流动性压力和60日尾部损失（CVaR）。增强模型只有在平均样本外Rank IC提高、高低风险十分位回撤差扩大、至少半数测试年度IC改善且具备不少于20个独立调仓期时，才替代基础模型生成正式风险分。

## Streamlit Community Cloud

1. 将本目录连同 `data/` 提交到公开 Git 仓库。
2. 在 Streamlit Community Cloud 选择仓库。
3. Main file path 指向 `Healthcare study/Barra收益归因分析/A-share/momentum_dashboard/streamlit_app.py`。
4. 部署即可；无需配置 Secrets。

## 分组规则

- A：动量分不低于70，20/60日趋势为正，站上20/60日均线，且过热分低于90。
- B：动量分不低于40，且20日跌幅不超过5%。
- C：其余股票或历史数据不足121个交易日。

## 评分扩展

看板同时提供趋势强度、子行业内估值分、追高风险和研究信号。估值分使用正PE_TTM与PB的子行业内相对排名；当前快照没有ROE、盈利增速或结构化新闻，因此质量/新闻分暂不虚构。

过去三年非重叠5/20/120日回测中，A组均没有表现出更高的平均未来收益，因此A/B/C只描述当前趋势确认程度，不应解释为未来收益评级。120日周期只有少量独立调仓期，统计稳定性较弱。回测未计交易成本、停牌成交限制、涨跌停和冲击成本，并使用当前股票池回看历史，存在幸存者偏差。

看板用于研究和监控，不构成投资建议。
