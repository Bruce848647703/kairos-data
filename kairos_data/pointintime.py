"""时点正确性（Point-In-Time, PIT）对齐：防止未来函数。

核心原则：在任意查询时点 ``t``，只能使用「截至 ``t`` 已经知道」的信息。

- ``asof_merge``：为 left 的每个时点，合并 right 中时间 ``<=`` 它的最近一条记录
  （backward 方向），从而只用已知信息。典型场景：把不定期发布的财报/公告/评级，
  对齐到每日行情上，且不会把「未来才发布」的值提前泄露给过去。
- ``lag``：把数据整体后移 n 期，使 t 时刻的输出只依赖 ``<= t-n`` 的输入。

这两个工具是构造无偏特征/标签的基础。
"""
from __future__ import annotations

from typing import Optional, Union

import numpy as np
import pandas as pd

FrameOrSeries = Union[pd.DataFrame, pd.Series]


def lag(obj: FrameOrSeries, periods: int = 1) -> FrameOrSeries:
    """滞后 n 期：t 时刻的输出 = t-periods 时刻的输入。

    ``periods >= 1`` 时只使用过去数据，天然防未来函数（等价于 ``pandas.shift``，
    但语义明确指向 PIT）。``periods < 0`` 为前移，会引入未来值，除非确有前视需求
    否则应避免。
    """
    return obj.shift(periods)


def asof_merge(left: pd.DataFrame, right: pd.DataFrame,
               on: Optional[str] = None,
               left_on: Optional[str] = None, right_on: Optional[str] = None,
               by: Optional[Union[str, list]] = None,
               direction: str = "backward",
               tolerance=None,
               allow_exact_matches: bool = True,
               suffixes=("_x", "_y")) -> pd.DataFrame:
    """按「时间就近且 <= 当时」合并两个序列（默认 backward，只用已知信息）。

    对 left 的每一行，取 right 中时间 ``<=`` 该行时间的最近一条记录合并进来，
    因此**不会引入未来数据**。``direction="forward"`` 会取未来值，默认禁止使用。

    支持两种输入形态：
    1) left/right 均为 ``DatetimeIndex`` 且未指定时间列：按索引合并，结果保留
       ``DatetimeIndex``。
    2) 通过 ``on`` 或 ``left_on``/``right_on`` 指定时间列名：按该列合并。

    ``by`` 可指定额外分组列（如 symbol），仅在同一组内做就近合并。结果保持 left
    的原始行顺序（内部按时间排序以满足 merge_asof 要求后再还原）。
    """
    use_index = (on is None) and (left_on is None) and (right_on is None)
    order_col = "_pit_order"
    if use_index:
        if not isinstance(left.index, pd.DatetimeIndex) or not isinstance(right.index, pd.DatetimeIndex):
            raise TypeError("未指定时间列时，left 与 right 都必须具有 DatetimeIndex")
        key = "_pit_time"
        orig_name = left.index.name
        l = left.reset_index()
        r = right.reset_index()
        l = l.rename(columns={l.columns[0]: key})
        r = r.rename(columns={r.columns[0]: key})
        l[order_col] = np.arange(len(l))
        l = l.sort_values(key)
        r = r.sort_values(key)
        merged = pd.merge_asof(
            l, r, on=key, by=by, direction=direction,
            tolerance=tolerance, allow_exact_matches=allow_exact_matches,
            suffixes=suffixes,
        )
        merged = merged.sort_values(order_col).drop(columns=order_col)
        merged = merged.set_index(key)
        merged.index.name = orig_name
        return merged

    lkey = on or left_on
    rkey = on or right_on
    l = left.copy()
    l[order_col] = np.arange(len(l))
    l = l.sort_values(lkey)
    r = right.sort_values(rkey)
    merged = pd.merge_asof(
        l, r, on=on, left_on=left_on, right_on=right_on, by=by,
        direction=direction, tolerance=tolerance,
        allow_exact_matches=allow_exact_matches, suffixes=suffixes,
    )
    merged = merged.sort_values(order_col).drop(columns=order_col)
    return merged
