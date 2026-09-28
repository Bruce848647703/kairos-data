# 数据声明 (DATA NOTICE) — 多资产 ETF

本目录 `data/etf/` 下的 `*.csv` 为**真实跨资产 ETF 日线行情**（前复权），用于多资产配置/GTAA 的研究与回测演示。

## 成分（资产类别）
- A 股权益：沪深300ETF(sh510300)、中证500ETF(sh510500)、创业板ETF(sz159915)
- 海外权益：纳指ETF(sh513100)、恒生ETF(sz159920)、中概互联ETF(sh513050)
- 商品：黄金ETF(sh518880)
- 债券：国债ETF(sh511010)
- 现金：货币ETF(sh511990)

## 来源
- 腾讯公开行情接口 `web.ifzq.gtimg.cn`（抓取代码见 `kairos_data/ashare.py`，原创）。
- 重新生成：`python examples/fetch_real.py`（或在代码中调用 `ashare.fetch_universe(universe.etf_symbols(), "data/etf")`）。

## 字段
`date, open, high, low, close, volume`（前复权；货币 ETF 价格恒近 100，作现金腿）。

## 许可与免责
- 数据版权归原作者 / 数据源所有；仅在**研究、学习、演示**目的下少量收录，**不用于商业用途**。
- 数据不保证准确/完整/及时；任何回测结果**不构成投资建议**。
- 如相关方要求移除，将第一时间删除。
