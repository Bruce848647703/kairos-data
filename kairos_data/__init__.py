"""Kairos Data —— 自研轻量级金融数据管道 / 行情库。

围绕「把原始行情变成干净、对齐、时点正确的数据集」这一目标，提供：
- schema:      核心数据结构 Bar/Candle 与面板数据约定。
- sources:     统一数据源接口 DataSource + CSV/Parquet/合成（GBM）实现。
- store:       本地数据集存储 DataStore（默认 CSV，Parquet 可选、缺失自动回退）。
- clean:       去重排序、按日历重建索引、限量前向填充、复权、异常值检测。
- calendar:    交易日历、多标的对齐、as-of 时点定位。
- pointintime: 防未来函数的时点对齐（as-of 合并、滞后）。
- pipeline:    把清洗步骤串成可复用管道。

设计原则：纯 numpy/pandas 依赖、离线可复现、纯函数优先、严格防未来函数。
"""
from __future__ import annotations

from .calendar import align, as_of, as_of_row, business_days
from .clean import (
    adjust_prices,
    dedup_sort,
    detect_outliers,
    ffill_policy,
    reindex_calendar,
)
from .pipeline import Pipeline, Step
from .pointintime import asof_merge, lag
from .schema import (
    OHLCV_COLUMNS,
    PRICE_COLUMNS,
    Bar,
    Candle,
    bars_to_frame,
    empty_panel,
    frame_to_panel,
    ohlc_is_consistent,
)
from .sources import CSVSource, DataSource, ParquetSource, SyntheticSource
from .store import DataStore
from . import ashare, universe
from .ashare import (
    TencentKlineSource,
    fetch_daily,
    fetch_daily_sina,
    fetch_daily_tencent,
    fetch_universe,
    load_ashare_panel,
    parse_sina_kline,
    parse_tencent_kline,
    rows_to_frame,
)
from .universe import (LIQUID_A_SHARES, SECTORS, ASSET_CLASS_ETFS, ASSET_CLASSES,
                        EXTENDED_NEW, EXT_SECTORS, EXTENDED_A_SHARES,
                        name_of, symbols, etf_symbols, extended_symbols)

__version__ = "0.1.0"

__all__ = [
    # schema
    "Bar", "Candle", "bars_to_frame", "frame_to_panel", "empty_panel",
    "ohlc_is_consistent", "OHLCV_COLUMNS", "PRICE_COLUMNS",
    # sources
    "DataSource", "CSVSource", "ParquetSource", "SyntheticSource",
    # store
    "DataStore",
    # clean
    "dedup_sort", "reindex_calendar", "ffill_policy", "adjust_prices", "detect_outliers",
    # calendar
    "business_days", "align", "as_of", "as_of_row",
    # pointintime
    "asof_merge", "lag",
    # pipeline
    "Pipeline", "Step",
    # ashare 真实数据
    "ashare", "universe", "TencentKlineSource", "fetch_daily", "fetch_daily_tencent",
    "fetch_daily_sina", "fetch_universe", "load_ashare_panel", "parse_tencent_kline",
    "parse_sina_kline", "rows_to_frame", "LIQUID_A_SHARES", "SECTORS", "symbols", "name_of",
    "ASSET_CLASS_ETFS", "ASSET_CLASSES", "etf_symbols",
    "EXTENDED_NEW", "EXT_SECTORS", "EXTENDED_A_SHARES", "extended_symbols",
    "__version__",
]
