# Kairos Data

> Kairos 量化系列的数据管道模块 —— 一个**自研、轻量、零重型依赖**的 Python 金融数据/行情库。

`kairos_data` 专注把杂乱的原始行情，变成**干净、日历对齐、时点正确（PIT）**的数据集，
为因子研究、回测、组合优化提供可靠的数据底座。核心代码全部原创，仅依赖 `numpy` 与 `pandas`，
存储默认使用 **CSV**（Parquet 为可选增强，缺失 `pyarrow` 时自动优雅回退）。

## 特性
- **统一数据源 `DataSource`**：抽象 `load(symbol, start, end)` 接口，内置
  `CSVSource`（本地目录）、`ParquetSource`（可选）、`SyntheticSource`（GBM 合成，确定性 seed，离线可复现）。
- **本地存储 `DataStore`**：`save/load/list/exists`，默认 CSV，`format="parquet"` 缺 `pyarrow` 时回退 CSV 并告警。
- **数据清洗 `clean`**：去重排序、按交易日历重建索引、**限量前向填充**、**前/后复权**、MAD/滚动 z **异常值检测**。
- **交易日历 `calendar`**：工作日日历、多标的 `align` 对齐、`as_of` 时点定位。
- **时点正确性 `pointintime`**：`asof_merge`（就近向后合并，只用已知信息）、`lag`（滞后 n 期），**杜绝未来函数**。
- **管道 `Pipeline`**：把多步清洗串成可复用、可审计的对象，`add_step`/`run`。
- **核心结构 `Bar`/`Candle`**：不可变 OHLCV 数据类 + 面板数据约定（index=日期, columns=资产）。

## 安装
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # 或 pip install numpy pandas
pip install -e ".[dev]"     # 需要跑测试时
pip install -e ".[parquet]" # 可选：启用 Parquet 存储
```

## 快速开始
### ① 合成行情 → 存储 → 读回
```python
from kairos_data import SyntheticSource, DataStore

src = SyntheticSource(seed=7, start="2021-01-01", periods=260)
raw = src.load("AAA")                    # OHLCV，DatetimeIndex，离线可复现

store = DataStore("./_store", format="csv")
store.save("AAA_raw", raw)
loaded = store.load("AAA_raw")           # 与 raw 逐位一致
```

### ② 清洗管道：去重 → 对齐日历 → 限量填充
```python
from kairos_data import Pipeline, dedup_sort, reindex_calendar, ffill_policy, business_days

cal = business_days(raw.index[0], raw.index[-1])
pipe = (Pipeline()
        .add_step(dedup_sort)
        .add_step(reindex_calendar, cal)
        .add_step(ffill_policy, limit=3))   # 最多连续填 3 天，避免陈旧外推
clean = pipe.run(raw[["close"]])
```

### ③ 复权与时点对齐
```python
from kairos_data import adjust_prices, asof_merge

hfq = adjust_prices(raw, factors, mode="hfq")   # 后复权：raw * f（锚定最早）
qfq = adjust_prices(raw, factors, mode="qfq")   # 前复权：raw * f / f_latest（锚定最新）

# 把不定期发布的事件（财报/评级）就近向后合并到每日行情，绝不泄露未来值
merged = asof_merge(daily_px, events, direction="backward")
```

完整可运行示例见 [`examples/demo.py`](examples/demo.py)。

## API 概览
| 模块 | 关键对象 | 说明 |
|---|---|---|
| `schema` | `Bar` `Candle` `bars_to_frame` `frame_to_panel` `ohlc_is_consistent` | 核心数据结构与面板约定 |
| `sources` | `DataSource` `CSVSource` `ParquetSource` `SyntheticSource` | 统一数据源接口与实现 |
| `store` | `DataStore` | 本地 CSV/Parquet 数据集存储 |
| `clean` | `dedup_sort` `reindex_calendar` `ffill_policy` `adjust_prices` `detect_outliers` | 清洗与复权 |
| `calendar` | `business_days` `align` `as_of` `as_of_row` | 交易日历与对齐 |
| `pointintime` | `asof_merge` `lag` | 时点正确性（防未来函数）|
| `pipeline` | `Pipeline` `Step` | 多步清洗管道 |

## 设计要点
- **时点正确性（PIT）**：`asof_merge` 默认 `backward` 方向，任一时刻只合并「<= 当时」的最近记录；
  `lag(n)` 使 t 时刻输出只依赖 `<= t-n` 的输入；`ffill_policy` 只用历史值向后填充。全链路杜绝前视偏差。
- **限量填充**：`ffill_policy(limit=k)` 最多连续填充 k 个缺口，避免长时间停牌被无限外推成陈旧数据。
- **复权语义清晰**：`factors` 为累计复权因子（基准日=1），后复权 `raw*f` 锚定最早、前复权 `raw*f/f_latest` 锚定最新；
  仅作用于价格列，成交量不复权。
- **存储稳健**：默认 CSV 零额外依赖；Parquet 为可选，缺 `pyarrow` 时构造即回退 CSV 并告警，CSV 往返用
  `float_precision="round_trip"` 保证逐位一致。
- **离线可复现**：合成源用 `SeedSequence([seed, crc32(symbol)])` 派生随机流，与调用顺序、其它 symbol 无关。

## 真实 A 股数据
除合成数据外，本库内置 **A 股真实行情适配器**（腾讯主源 / 新浪回退，原创 HTTP 实现）：

```python
from kairos_data import ashare, universe

# 1) 联网抓取一篮子流动 A 股前复权日线到本地 CSV
ashare.fetch_universe(universe.symbols(), "data/ashare", start="2016-01-01")

# 2) 离线读取为对齐的价格/成交量面板（自动处理停牌、上市日、非正价）
prices, volumes = ashare.load_ashare_panel("data/ashare")   # DataFrame: index=交易日, columns=symbol
```
- `universe.LIQUID_A_SHARES` / `SECTORS`：精选跨行业股票池与行业分组。
- 仓库已随附一份真实数据集 `data/ashare/*.csv`（约 8 年日线，38 只），见 [`data/ashare/DATA_NOTICE.md`](data/ashare/DATA_NOTICE.md)。
- 抓取脚本：`python examples/fetch_real.py`（需联网）。解析器为纯函数，测试**离线**可跑。

> 数据来自公开行情接口，仅用于研究演示、版权归原作者所有，不构成投资建议。

## 测试
```bash
make test          # 或 python -m pytest -q
```
测试全部离线、固定 seed；存储/数据源测试使用 pytest `tmp_path`，默认走 CSV，不依赖 Parquet。

## 项目结构
```
kairos_data/    核心包（schema / sources / store / clean / calendar / pointintime / pipeline）
examples/       可运行示例
tests/          pytest 测试
```

## 许可
MIT © 2026 Bruce848647703，见 [LICENSE](LICENSE)。

## 参考与致谢
本项目为**独立原创实现**，未复制任何第三方代码。设计思路受业界通用数据管道范式
（复权、交易日历对齐、时点正确性/PIT、本地列式与 CSV 存储）启发，
在此向开源量化社区致谢。算法与接口均为本仓库自研。
