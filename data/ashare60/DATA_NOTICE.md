# 数据声明 (DATA NOTICE)

本目录 `data/ashare/` 下的 `*.csv` 为**真实 A 股日线行情**（后复权 hfq），用于本开源项目的研究与回测演示。

## 来源
- 主数据源：腾讯公开行情接口（后复权 hfq） `web.ifzq.gtimg.cn`
- 回退数据源：新浪公开行情接口 `money.finance.sina.com.cn`
- 抓取代码：`kairos_data/ashare.py`（本项目原创）；重新生成：`python examples/fetch_real.py`

## 字段
`date, open, high, low, close, volume`（后复权 hfq；volume 单位为「手」，以数据源口径为准）。

## 许可与免责
- 数据版权归原作者 / 数据源所有。本仓库仅在**研究、学习、演示**目的下少量收录，**不用于任何商业用途**，不主张对数据本身的所有权。
- 数据**不保证准确、完整或及时**；后复权(hfq)口径以数据源为准；hfq 价格水平被放大但收益率正确，适合回测。
- 任何基于本数据的回测结果**不构成投资建议**。
- 若数据源或相关方要求移除，请联系仓库维护者，将第一时间删除。

## 可复现
本数据集可由 `examples/fetch_real.py` 随时按 `universe.LIQUID_A_SHARES` 重新抓取生成；
如需避免分发原始数据，可删除本目录并在使用时联网重新抓取。

## 扩展池说明
本目录 `data/ashare60/` 为**扩展 60 只**数据集（38 核心 + 22 新增龙头，覆盖交运/地产/建筑/农业/公用/国防/通信/机械/材料等更多行业），对应 `universe.EXTENDED_A_SHARES` / `extended_symbols()`。
默认核心 38 只池在 `data/ashare/`（与既有下游结果一致）；扩展池用于更宽截面的因子/策略研究（各 example 用 `--data-dir` 指向本目录即可）。
