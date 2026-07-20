# A股医疗动量看板

面向公开部署的 Streamlit 应用，覆盖 `Full version/universe` 中的310只A股医疗相关股票。

## 本地运行

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## 更新数据快照

在 `momentum_dashboard` 目录运行：

```bash
export TUSHARE_TOKEN="your-token"
python update_prices.py --end-date YYYYMMDD
python build_snapshot.py
```

`update_prices.py` 按交易日批量补充日线与复权因子，并重建前复权宽表；`build_snapshot.py` 随后读取相邻的 `../Full version/universe` 数据，生成部署所需的三个轻量文件：

- `data/momentum_snapshot.csv`
- `data/subindustry_snapshot.csv`
- `data/price_history.csv.gz`

应用运行时不会调用 Tushare，也不需要任何密钥。先用原有数据流程更新股票池和前复权行情，再重新运行构建脚本即可更新公开看板。

## Streamlit Community Cloud

1. 将本目录连同 `data/` 提交到公开 Git 仓库。
2. 在 Streamlit Community Cloud 选择仓库。
3. Main file path 指向 `Barra收益归因分析/A-share/momentum_dashboard/streamlit_app.py`。
4. 部署即可；无需配置 Secrets。

## 分组规则

- A：动量分不低于70，20/60日趋势为正，站上20/60日均线，且过热分低于85。
- B：动量分不低于40，且20日跌幅不超过5%。
- C：其余股票或历史数据不足121个交易日。

看板用于研究和监控，不构成投资建议。
