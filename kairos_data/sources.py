"""行情数据源：统一抽象接口 + 多种实现。

``DataSource`` 定义最小契约 ``load(symbol, start, end) -> DataFrame``，返回遵循
``schema`` 约定的 DataFrame：``DatetimeIndex`` + ``open/high/low/close/volume`` 列。

实现：
- ``CSVSource``：从本地目录按 symbol 读取 CSV 行情（默认、零额外依赖）。
- ``ParquetSource``：读取 Parquet（可选，依赖 pyarrow；缺失时给出清晰报错）。
- ``SyntheticSource``：几何布朗运动生成合成 OHLCV（确定性 seed，无需联网），
  供测试与示例使用。

设计意图：把「数据从哪来」抽象成统一接口，上层清洗/存储/回测只依赖 DataFrame
形态，可自由替换真实源或合成源。
"""
from __future__ import annotations

import importlib.util
import os
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, List, Optional, Sequence

import numpy as np
import pandas as pd

from .schema import OHLCV_COLUMNS


def _pyarrow_available() -> bool:
    """检测 pyarrow 是否可导入（不真正加载重依赖）。"""
    return importlib.util.find_spec("pyarrow") is not None


def _to_ts(x) -> Optional[pd.Timestamp]:
    """把任意日期输入规范化为 ``pd.Timestamp``；None 原样返回。"""
    return None if x is None else pd.Timestamp(x)


class DataSource(ABC):
    """数据源抽象基类。

    子类实现 ``load``，按 symbol 与时间范围返回 OHLCV DataFrame。可选实现
    ``symbols`` 返回可用标的清单。
    """

    @abstractmethod
    def load(self, symbol: str, start=None, end=None) -> pd.DataFrame:
        """加载单个 symbol 在 [start, end] 区间的行情。"""
        raise NotImplementedError

    def symbols(self) -> List[str]:
        """返回可用标的清单（可选能力，默认空列表）。"""
        return []

    @staticmethod
    def _slice(df: pd.DataFrame, start, end) -> pd.DataFrame:
        """按 [start, end] 闭区间裁剪时间索引（None 表示不限）。"""
        s, e = _to_ts(start), _to_ts(end)
        if s is not None:
            df = df.loc[df.index >= s]
        if e is not None:
            df = df.loc[df.index <= e]
        return df

    @staticmethod
    def _normalize_columns(df: pd.DataFrame, lowercase: bool = True) -> pd.DataFrame:
        """规范化列名（去空白、可选转小写），并解析/排序 DatetimeIndex、去重。"""
        out = df.copy()
        if lowercase:
            out.columns = [str(c).strip().lower() for c in out.columns]
        out = out.sort_index()
        out = out[~out.index.duplicated(keep="last")]
        return out


@dataclass
class CSVSource(DataSource):
    """从目录读取每 symbol 一个 CSV 文件的行情源。

    参数
    ----
    root:          CSV 所在目录。
    datetime_col:  时间列名（读入后转为索引）；若为 None，则直接用第 0 列作索引。
    pattern:       文件名模板，``{symbol}`` 会被替换。
    lowercase_columns: 是否把列名转小写以匹配标准 OHLCV 命名。
    """

    root: str
    datetime_col: Optional[str] = "datetime"
    pattern: str = "{symbol}.csv"
    lowercase_columns: bool = True

    def _path(self, symbol: str) -> str:
        return os.path.join(self.root, self.pattern.format(symbol=symbol))

    def load(self, symbol: str, start=None, end=None) -> pd.DataFrame:
        path = self._path(symbol)
        if not os.path.exists(path):
            raise FileNotFoundError(f"未找到 symbol '{symbol}' 的 CSV 文件: {path}")
        # float_precision="round_trip" 保证 float64 经 CSV 往返后逐位一致。
        df = pd.read_csv(path, float_precision="round_trip")
        df.columns = [str(c).strip().lower() for c in df.columns] if self.lowercase_columns else list(df.columns)
        if self.datetime_col is not None and self.datetime_col in df.columns:
            df[self.datetime_col] = pd.to_datetime(df[self.datetime_col])
            df = df.set_index(self.datetime_col)
        elif self.datetime_col is None:
            first = df.columns[0]
            df[first] = pd.to_datetime(df[first])
            df = df.set_index(first)
        else:
            raise KeyError(f"CSV 缺少时间列 '{self.datetime_col}'，现有列: {list(df.columns)}")
        df.index.name = "datetime"
        df = self._normalize_columns(df, self.lowercase_columns)
        return self._slice(df, start, end)

    def symbols(self) -> List[str]:
        if not os.path.isdir(self.root):
            return []
        suffix = self.pattern.split("{symbol}")[-1] or ".csv"
        out = []
        for fn in sorted(os.listdir(self.root)):
            if fn.endswith(suffix):
                out.append(fn[: -len(suffix)])
        return out


@dataclass
class ParquetSource(DataSource):
    """从目录读取 Parquet 行情源（可选，依赖 pyarrow）。

    构造时若检测到 pyarrow 缺失，会抛出清晰的 ``ImportError``，提示改用
    ``CSVSource`` 或安装 pyarrow。
    """

    root: str
    datetime_col: Optional[str] = None
    pattern: str = "{symbol}.parquet"
    lowercase_columns: bool = True

    def __post_init__(self) -> None:
        if not _pyarrow_available():
            raise ImportError(
                "ParquetSource 需要 pyarrow 支持，但当前环境未检测到。"
                "请执行 `pip install pyarrow`，或改用 CSVSource / SyntheticSource"
                "（本库默认以 CSV 作为存储与读取格式）。"
            )

    def _path(self, symbol: str) -> str:
        return os.path.join(self.root, self.pattern.format(symbol=symbol))

    def load(self, symbol: str, start=None, end=None) -> pd.DataFrame:
        path = self._path(symbol)
        if not os.path.exists(path):
            raise FileNotFoundError(f"未找到 symbol '{symbol}' 的 Parquet 文件: {path}")
        df = pd.read_parquet(path)
        if self.datetime_col is not None and self.datetime_col in df.columns:
            df[self.datetime_col] = pd.to_datetime(df[self.datetime_col])
            df = df.set_index(self.datetime_col)
        elif not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = "datetime"
        df = self._normalize_columns(df, self.lowercase_columns)
        return self._slice(df, start, end)

    def symbols(self) -> List[str]:
        if not os.path.isdir(self.root):
            return []
        suffix = self.pattern.split("{symbol}")[-1] or ".parquet"
        out = []
        for fn in sorted(os.listdir(self.root)):
            if fn.endswith(suffix):
                out.append(fn[: -len(suffix)])
        return out


@dataclass
class SyntheticSource(DataSource):
    """几何布朗运动（GBM）合成 OHLCV 数据源，确定性、离线、可复现。

    收盘按 GBM 生成：``log(S_t/S_{t-1}) = (mu - σ²/2)Δt + σ√Δt·z``；开盘取上一
    收盘（首日取 ``s0``）；高/低在 ``max/min(open, close)`` 基础上叠加非负的日内
    波动，从而保证 ``low <= open/close <= high`` 恒成立；成交量为对数正态正值。

    随机性由 ``seed`` 与 ``symbol`` 共同确定（用 CRC32 派生每 symbol 的稳定熵），
    因此同一 (seed, symbol, 参数) 两次调用结果完全一致，且与调用顺序、其它 symbol
    无关。

    参数
    ----
    seed:            基础随机种子。
    start/periods:   默认起始日期与 bar 数（未显式给 start/end 时使用）。
    mu/sigma:        年化漂移与波动，按 ``periods_per_year`` 折算到每期。
    s0:              初始价格。
    intraday_vol:    日内高低相对 open/close 的波动幅度（非负）。
    base_volume:     成交量中枢。
    freq:            日期频率，默认 "B"（工作日）。
    """

    seed: int = 42
    start: str = "2020-01-01"
    periods: int = 252
    mu: float = 0.08
    sigma: float = 0.25
    s0: float = 100.0
    intraday_vol: float = 0.01
    base_volume: float = 1_000_000.0
    periods_per_year: int = 252
    freq: str = "B"

    DEFAULT_SYMBOLS: ClassVar[Sequence[str]] = ("AAA", "BBB", "CCC")

    def _dates(self, start, end) -> pd.DatetimeIndex:
        s = _to_ts(start) if start is not None else _to_ts(self.start)
        if end is not None:
            return pd.date_range(start=s, end=_to_ts(end), freq=self.freq)
        return pd.date_range(start=s, periods=self.periods, freq=self.freq)

    def _rng_for(self, symbol: str) -> np.random.Generator:
        """为每个 symbol 派生稳定的随机流（与调用顺序无关）。"""
        entropy = int(zlib.crc32(str(symbol).encode("utf-8")))
        ss = np.random.SeedSequence([int(self.seed), entropy])
        return np.random.default_rng(ss)

    def load(self, symbol: str, start=None, end=None) -> pd.DataFrame:
        dates = self._dates(start, end)
        n = len(dates)
        cols = list(OHLCV_COLUMNS)
        if n == 0:
            return pd.DataFrame(columns=cols, index=dates).rename_axis("datetime")

        rng = self._rng_for(symbol)
        dt = 1.0 / float(self.periods_per_year)
        drift = (self.mu - 0.5 * self.sigma ** 2) * dt
        z = rng.standard_normal(n)
        log_ret = drift + self.sigma * np.sqrt(dt) * z
        close = self.s0 * np.exp(np.cumsum(log_ret))

        open_ = np.empty(n, dtype="float64")
        open_[0] = self.s0
        if n > 1:
            open_[1:] = close[:-1]

        upper = np.maximum(open_, close)
        lower = np.minimum(open_, close)
        hi = np.clip(np.abs(rng.standard_normal(n)) * self.intraday_vol, 0.0, 0.9)
        lo = np.clip(np.abs(rng.standard_normal(n)) * self.intraday_vol, 0.0, 0.9)
        high = upper * (1.0 + hi)
        low = lower * (1.0 - lo)

        vol = self.base_volume * np.exp(rng.standard_normal(n) * 0.3)
        vol = np.clip(vol, 1.0, None)

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=dates,
        )
        df.index.name = "datetime"
        return df[cols]

    def symbols(self) -> List[str]:
        return list(self.DEFAULT_SYMBOLS)
