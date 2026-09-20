"""核心数据结构与面板数据约定。

本模块定义全库统一的行情数据形态：
- ``Bar``（又名 ``Candle`` / K 线）：单标的、单时点的一根 OHLCV bar，用 frozen
  dataclass 承载，保证不可变、可哈希。
- **面板约定**：``pandas.DataFrame``，``index`` 为 ``DatetimeIndex``（时间），
  ``columns`` 为资产（symbol）。这是 clean / calendar / store / pointintime 等
  模块对齐的标准形态，向量化计算均基于它。

设计意图：单根 bar 用不可变数据类，便于做字典键与集合运算；批量数据用面板
DataFrame，便于向量化。两者通过 ``bars_to_frame`` / ``frame_to_panel`` 互转。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

#: 统一的 OHLCV 列名（小写）。数据源解析与清洗模块据此识别列。
OHLCV_COLUMNS: Sequence[str] = ("open", "high", "low", "close", "volume")
#: 价格列（不含成交量），复权等操作只作用于这些列。
PRICE_COLUMNS: Sequence[str] = ("open", "high", "low", "close")

#: 面板约定：索引名与列名。仅为文档/一致性提示，实际不强制。
PANEL_INDEX_NAME = "datetime"
PANEL_COLUMNS_NAME = "symbol"


@dataclass(frozen=True)
class Bar:
    """单根行情 bar（OHLCV）。

    参数
    ----
    symbol:   标的代码。
    datetime: bar 的时间戳；构造时统一转为 ``pd.Timestamp``。
    open/high/low/close: 当期开/高/低/收四价，统一转为 ``float``。
    volume:   成交量（或成交额），默认 0。

    ``frozen=True`` 保证不可变、可哈希，可作为字典键或集合元素；
    ``__post_init__`` 仍会对时间戳与数值做规范化（通过 ``object.__setattr__``）。
    """

    symbol: str
    datetime: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol))
        object.__setattr__(self, "datetime", pd.Timestamp(self.datetime))
        for fname in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, fname, float(getattr(self, fname)))

    def is_valid(self, tol: float = 1e-9) -> bool:
        """校验 OHLC 关系是否合理：``low <= open/close <= high``，且价格非负。"""
        o, h, low, c = self.open, self.high, self.low, self.close
        if min(o, h, low, c) < -tol:
            return False
        return (low <= o + tol) and (low <= c + tol) and (o <= h + tol) and (c <= h + tol)

    def typical_price(self) -> float:
        """典型价 = (high + low + close) / 3，常用于成交量加权指标。"""
        return (self.high + self.low + self.close) / 3.0

    def to_dict(self) -> Dict[str, object]:
        """转为普通 dict，便于批量构造 DataFrame。"""
        d = asdict(self)
        d["datetime"] = self.datetime
        return d


#: K 线（Candle）与 Bar 同义，提供别名以贴合不同使用习惯。
Candle = Bar


def bars_to_frame(bars: Iterable[Bar]) -> pd.DataFrame:
    """把一批 ``Bar`` 转成 tidy DataFrame。

    返回：``DatetimeIndex`` + ``symbol`` 列 + OHLCV 列，按时间升序。空输入返回
    带标准列名的空表。
    """
    rows: List[Dict[str, object]] = [b.to_dict() for b in bars]
    if not rows:
        return pd.DataFrame(columns=["symbol", *OHLCV_COLUMNS])
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    cols = ["symbol", *[c for c in OHLCV_COLUMNS if c in df.columns]]
    return df[cols]


def frame_to_panel(long_df: pd.DataFrame, field: str = "close",
                   symbol_col: str = "symbol") -> pd.DataFrame:
    """把长表透视为单字段面板（index=时间, columns=symbol, 值=field）。

    长表需含 ``DatetimeIndex``（或时间列）、``symbol_col`` 列与 ``field`` 列。
    同一 (时间, symbol) 不应重复；如有重复请先用 ``clean.dedup_sort`` 处理。
    """
    if field not in long_df.columns:
        raise KeyError(f"缺少字段列 '{field}'，现有列: {list(long_df.columns)}")
    if symbol_col not in long_df.columns:
        raise KeyError(f"缺少标的列 '{symbol_col}'，现有列: {list(long_df.columns)}")
    tmp = long_df.reset_index()
    time_col = tmp.columns[0]
    tmp[time_col] = pd.to_datetime(tmp[time_col])
    panel = tmp.pivot(index=time_col, columns=symbol_col, values=field)
    panel.index.name = PANEL_INDEX_NAME
    panel.columns.name = None
    return panel.sort_index()


def empty_panel(dates: Iterable, symbols: Iterable[str],
                fill: Optional[float] = None) -> pd.DataFrame:
    """构造一个空面板（index=dates, columns=symbols），可选用 fill 填充。"""
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    cols = list(symbols)
    data = np.full((len(idx), len(cols)), np.nan if fill is None else float(fill))
    return pd.DataFrame(data, index=idx, columns=cols)


def ohlc_is_consistent(df: pd.DataFrame, tol: float = 1e-9) -> bool:
    """检查 OHLC DataFrame 是否逐行满足 ``low <= open/close <= high``。

    仅对存在的列做检查；缺列则跳过该约束。用于校验数据源输出的合理性。
    """
    needed = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if "high" not in needed or "low" not in needed:
        return True
    ok = pd.Series(True, index=df.index)
    low = df["low"]
    high = df["high"]
    if "open" in needed:
        ok &= (low <= df["open"] + tol) & (df["open"] <= high + tol)
    if "close" in needed:
        ok &= (low <= df["close"] + tol) & (df["close"] <= high + tol)
    ok &= low <= high + tol
    return bool(ok.all())
