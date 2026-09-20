"""数据清洗：去重排序、按日历重建索引、限量前向填充、复权、异常值检测。

所有函数均为**纯函数**：接收 DataFrame/Series，返回新对象，不修改输入；且只用
「截至当时」的历史数据，绝不引入未来信息（前向填充只用过去值）。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .schema import PRICE_COLUMNS

FrameOrSeries = Union[pd.DataFrame, pd.Series]

#: 复权模式别名归一化。
_FORWARD_MODES = {"forward", "hfq", "post", "postadjust", "后复权"}
_BACKWARD_MODES = {"backward", "qfq", "pre", "preadjust", "前复权"}


def dedup_sort(df: FrameOrSeries, keep: str = "last") -> FrameOrSeries:
    """按索引（时间）去重并升序排列。

    keep: 重复索引保留哪一条，"last"（默认）/"first"/False。
    对 OHLCV 面板而言，保证时间序列单调且索引唯一，是后续对齐的前提。
    """
    out = df[~df.index.duplicated(keep=keep)]
    return out.sort_index()


def reindex_calendar(df: FrameOrSeries, calendar: Iterable,
                     fill: Optional[float] = None) -> FrameOrSeries:
    """按交易日历重建索引。

    calendar: 目标 ``DatetimeIndex`` 或可转为日期的可迭代对象。缺失时点填 NaN
    （或给定的 ``fill`` 值）；不在日历中的多余时点被丢弃。用于把不同标的对齐到
    统一日历。调用前应保证 ``df`` 索引唯一（见 ``dedup_sort``）。
    """
    cal = pd.DatetimeIndex(pd.to_datetime(list(calendar)))
    cal = cal.unique().sort_values()
    out = df.reindex(cal)
    if fill is not None:
        out = out.fillna(fill)
    return out


def ffill_policy(df: FrameOrSeries, limit: Optional[int] = None) -> FrameOrSeries:
    """限量前向填充：用最近一个有效值向后填充缺失，最多连续填充 ``limit`` 个。

    - ``limit=None``：不限连续填充个数。
    - ``limit=k``：最多连续填充 k 个 NaN，超过则保留 NaN（避免长时间停牌被无限
      外推，产生陈旧数据）。

    只用历史（过去）值向后填充，不引入未来数据。
    """
    return df.ffill(limit=limit)


def adjust_prices(df: pd.DataFrame, factors, mode: str = "forward",
                  columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """用给定复权因子对价格列做前/后复权。

    参数
    ----
    factors: 累计复权因子。可为标量、dict 或带 ``DatetimeIndex`` 的 ``Series``
             （基准日通常为 1.0，随除权除息事件变化）。会按 ``df.index`` 对齐，
             缺口先前向填充、首部再后向填充。
    mode:
      - "forward"/"hfq"/"后复权"：``adj = raw * f``，以最早（基准日）为锚，
        基准日价格不变，其后价格按因子放大/缩小。
      - "backward"/"qfq"/"前复权"：``adj = raw * f / f_latest``，以最新日为锚，
        最新价格不变，历史价格按因子缩放。
    columns: 要复权的列；默认自动识别 open/high/low/close，若无这些列则作用于
             全部数值列（volume 除外）。**成交量不复权**。

    说明：对多资产面板，factors 作为「按日期」的统一因子作用于所有列；若各资产
    复权因子不同，请按列/按资产分别调用。
    """
    mode_l = str(mode).lower().strip()
    if mode_l in _FORWARD_MODES:
        kind = "forward"
    elif mode_l in _BACKWARD_MODES:
        kind = "backward"
    else:
        raise ValueError(f"未知复权模式 '{mode}'，应为 forward/后复权 或 backward/前复权")

    f = _align_factors(factors, df.index)
    if kind == "backward":
        valid = f.dropna()
        if len(valid) == 0:
            raise ValueError("复权因子全为 NaN，无法做前复权")
        f = f / float(valid.iloc[-1])

    cols = _resolve_price_columns(df, columns)
    out = df.copy()
    out[cols] = out[cols].mul(f, axis=0)
    return out


def detect_outliers(df: FrameOrSeries, method: str = "mad", threshold: float = 3.0,
                    window: Optional[int] = None) -> FrameOrSeries:
    """检测异常值，返回与输入同形状的布尔掩码（True=疑似异常）。

    method:
      - "mad"（默认）：基于中位数与中位绝对差的稳健 z 分数，适合全局检测。
        ``z = 0.6745 * (x - median) / MAD``，``|z| > threshold`` 记为异常。对常量列
        （MAD=0）不误报。
      - "rolling"：滚动均值/标准差 z 分数（窗口长度 ``window``，默认 20）。每个点
        与「不含自身」的前 window 个历史值比较：``z = (x - 前窗均值) / 前窗标准差``，
        ``|z| > threshold`` 记为异常。既防未来函数，也避免异常点稀释自身窗口统计量。
    逐列独立计算；NaN 不视为异常。
    """
    m = str(method).lower().strip()
    is_series = isinstance(df, pd.Series)
    data = df.astype("float64")
    if is_series:
        data = data.to_frame("__value__")

    if m in ("mad", "median"):
        mask = _mad_outliers(data, float(threshold))
    elif m in ("rolling", "z", "zscore"):
        w = int(window or 20)
        mask = _rolling_outliers(data, w, float(threshold))
    else:
        raise ValueError(f"未知异常检测方法 '{method}'，应为 'mad' 或 'rolling'")

    if is_series:
        return mask["__value__"]
    return mask


def _mad_outliers(data: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """基于 MAD 的稳健离群检测（逐列）。"""
    med = data.median()                       # 每列中位数
    dev = data.sub(med)                        # 广播到列
    mad = dev.abs().median()                   # 每列 MAD
    denom = mad.replace(0, np.nan)             # 常量列 -> NaN，避免除零误报
    z = 0.6745 * dev.div(denom)
    return (z.abs() > threshold).fillna(False)


def _rolling_outliers(data: pd.DataFrame, window: int, threshold: float) -> pd.DataFrame:
    """基于滚动均值/标准差的离群检测（逐列，trailing 窗口）。

    每个点与「不含自身」的前 window 个历史值的均值/标准差比较（``shift(1)``）：
    一方面杜绝未来函数，另一方面避免异常点抬高自身窗口统计量而被稀释漏检。
    """
    min_periods = max(2, window // 2)
    roll = data.rolling(window=window, min_periods=min_periods)
    mean = roll.mean().shift(1)
    std = roll.std().shift(1)
    denom = std.replace(0, np.nan)
    z = (data - mean) / denom
    return (z.abs() > threshold).fillna(False)


def _align_factors(factors, index: pd.Index) -> pd.Series:
    """把复权因子对齐到目标 index，返回 float Series。"""
    if isinstance(factors, (int, float, np.number)):
        return pd.Series(float(factors), index=index, dtype="float64")
    if isinstance(factors, dict):
        factors = pd.Series(factors)
    if isinstance(factors, pd.DataFrame):
        if factors.shape[1] != 1:
            raise TypeError("DataFrame 形式的复权因子必须只有一列")
        factors = factors.iloc[:, 0]
    if isinstance(factors, pd.Series):
        s = factors.astype("float64").copy()
        s.index = pd.to_datetime(s.index)
        s = s.reindex(index).ffill().bfill()
        return s
    raise TypeError("factors 需为 标量 / dict / Series / 单列 DataFrame")


def _resolve_price_columns(df: pd.DataFrame,
                           columns: Optional[Sequence[str]]) -> List[str]:
    """确定需要复权的列。"""
    if columns is not None:
        cols = [c for c in columns if c in df.columns]
        if not cols:
            raise KeyError(f"指定的复权列 {list(columns)} 均不在 DataFrame 中")
        return cols
    present = [c for c in PRICE_COLUMNS if c in df.columns]
    if present:
        return present
    numeric = list(df.select_dtypes(include=[np.number]).columns)
    return [c for c in numeric if c != "volume"]
