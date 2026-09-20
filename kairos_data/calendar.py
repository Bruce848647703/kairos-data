"""交易日历与多标的对齐工具。

提供：
- ``business_days``：生成工作日日历，可剔除自定义假日。
- ``align``：把一组 DataFrame（通常是不同资产/来源的面板）对齐到共同索引。
- ``as_of``：给定查询时点，定位「<= 当时」的最近一个已发布时点（时点正确性）。

设计意图：真实数据各标的的交易日可能不一致（停牌、上市时间不同、来源差异），
统一日历与对齐是后续清洗、合并、回测的前提。
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Union

import pandas as pd

Indexable = Union[pd.DataFrame, pd.Series, pd.Index]


def business_days(start, end=None, periods: Optional[int] = None,
                  freq: str = "B", holidays: Optional[Iterable] = None) -> pd.DatetimeIndex:
    """生成工作日日历。

    参数
    ----
    start:    起始日期。
    end:      结束日期（闭区间）；与 ``periods`` 二选一。
    periods:  生成 bar 数（当未给 end 时使用）。
    freq:     频率，默认 "B"（工作日）。
    holidays: 需额外剔除的日期（可迭代）。

    返回 ``DatetimeIndex``。
    """
    if end is None and periods is None:
        raise ValueError("必须提供 end 或 periods 之一")
    if end is not None:
        idx = pd.date_range(start=start, end=end, freq=freq)
    else:
        idx = pd.date_range(start=start, periods=int(periods), freq=freq)
    if holidays:
        hol = pd.to_datetime(list(holidays))
        idx = idx.difference(hol)
    return idx


def align(frames: Sequence[pd.DataFrame], how: str = "inner",
          on_columns: bool = False) -> List[pd.DataFrame]:
    """把一组 DataFrame 对齐到共同索引（可选同时对齐列）。

    参数
    ----
    frames:     DataFrame 列表。
    how:        "inner" 取索引交集（只保留全部共有的时点）；
                "outer" 取索引并集（缺失处留 NaN）。
    on_columns: 为 True 时同样按 how 对齐列。

    返回与输入同顺序的对齐后 DataFrame 列表。常用于把多只股票的收盘价面板对齐到
    同一套交易日。
    """
    if not frames:
        return []
    h = str(how).lower()
    if h not in ("inner", "outer"):
        raise ValueError("how 应为 'inner' 或 'outer'")
    frames = list(frames)

    idx = pd.DatetimeIndex(frames[0].index)
    for f in frames[1:]:
        idx = idx.union(f.index) if h == "outer" else idx.intersection(f.index)
    idx = idx.sort_values()

    cols = None
    if on_columns:
        cols = frames[0].columns
        for f in frames[1:]:
            cols = cols.union(f.columns) if h == "outer" else cols.intersection(f.columns)
        cols = cols.sort_values()

    out: List[pd.DataFrame] = []
    for f in frames:
        g = f.reindex(index=idx)
        if cols is not None:
            g = g.reindex(columns=cols)
        out.append(g)
    return out


def as_of(index: Indexable, when) -> Optional[pd.Timestamp]:
    """返回 ``index`` 中 ``<= when`` 的最后一个时点；若无则返回 None。

    这是时点正确性（PIT）的基础查询：给定查询时刻 ``when``，定位当时手上「已经
    发布」的最近数据点，绝不返回未来时点。``index`` 可为 DatetimeIndex，或带索引
    的 Series/DataFrame（取其 index）。
    """
    idx = index
    if isinstance(idx, (pd.Series, pd.DataFrame)):
        idx = idx.index
    idx = pd.DatetimeIndex(idx).sort_values()
    if len(idx) == 0:
        return None
    w = pd.Timestamp(when)
    pos = int(idx.searchsorted(w, side="right")) - 1
    if pos < 0:
        return None
    return idx[pos]


def as_of_row(df: pd.DataFrame, when) -> Optional[pd.Series]:
    """返回 DataFrame 在 ``when`` 时点「已知」的最近一行（Series）；无则 None。"""
    label = as_of(df.index, when)
    if label is None:
        return None
    return df.loc[label]
