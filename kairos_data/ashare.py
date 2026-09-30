"""A 股真实行情适配器（公开行情接口）。

数据源：
- 主源 腾讯行情 ``web.ifzq.gtimg.cn``（默认后复权 hfq 日 K，支持按日期窗口分页取长历史）。
- 回退 新浪行情 ``money.finance.sina.com.cn``（取最近 N 个交易日）。

设计：
- 解析器 ``parse_tencent_kline`` / ``parse_sina_kline`` 为**纯函数**，可离线单测。
- 网络抓取仅在 ``fetch_*`` 中发生；测试不联网。
- ``load_ashare_panel`` 从本地 CSV 目录（已抓取/已提交的数据集）读出对齐的价格/成交量面板。

合规：数据来自公开行情接口，仅用于研究与演示，版权归原作者/数据源所有；见仓库 ``DATA_NOTICE.md``。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .schema import OHLCV_COLUMNS
from .sources import DataSource

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
Row = Tuple[str, float, float, float, float, float]  # date, open, high, low, close, volume


# ------------------------------------------------------------------ 解析器（纯函数，可离线测）
def parse_tencent_kline(node: dict) -> List[Row]:
    """解析腾讯返回的单个 symbol 节点 -> [(date, o, h, l, c, v), ...]。

    腾讯 qfqday/hfqday/day 每行形如 [date, open, close, high, low, volume, ...]。
    """
    arr = node.get("qfqday") or node.get("hfqday") or node.get("day") or []
    out: List[Row] = []
    for r in arr:
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        try:
            out.append((str(r[0]), float(r[1]), float(r[3]), float(r[4]), float(r[2]), float(r[5])))
        except (TypeError, ValueError):
            continue
    return out


def parse_sina_kline(arr: Sequence[dict]) -> List[Row]:
    """解析新浪 getKLineData 返回 -> [(date, o, h, l, c, v), ...]。

    新浪每项形如 {"day":..,"open":..,"high":..,"low":..,"close":..,"volume":..}。
    """
    out: List[Row] = []
    for r in arr or []:
        if not isinstance(r, dict):
            continue
        try:
            out.append((str(r["day"]), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]), float(r.get("volume", 0.0))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def rows_to_frame(rows: Sequence[Row]) -> pd.DataFrame:
    """把解析出的行转为标准 OHLCV DataFrame（DatetimeIndex，去重升序）。"""
    if not rows:
        return pd.DataFrame(columns=list(OHLCV_COLUMNS))
    df = pd.DataFrame([{"date": r[0], "open": r[1], "high": r[2],
                        "low": r[3], "close": r[4], "volume": r[5]} for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates("date").set_index("date").sort_index()
    return df[list(OHLCV_COLUMNS)]


# ------------------------------------------------------------------ 网络抓取
def _http_json(url: str, headers: Optional[dict] = None, tries: int = 3, timeout: int = 25):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 + k)
    raise RuntimeError(f"HTTP 抓取失败: {url} ({last})")


def _date_windows(start: str, end: str, step_days: int = 700) -> List[Tuple[str, str]]:
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    out = []
    while s <= e:
        w = min(s + dt.timedelta(days=step_days), e)
        out.append((s.isoformat(), w.isoformat()))
        s = w + dt.timedelta(days=1)
    return out


def fetch_daily_tencent(symbol: str, start: str = "2016-01-01", end: Optional[str] = None,
                        adjust: str = "hfq", delay: float = 0.15) -> pd.DataFrame:
    """腾讯源：按日期窗口分页抓取后复权(hfq)日线，拼接为 OHLCV DataFrame。"""
    end = end or dt.date.today().isoformat()
    rows: Dict[str, Row] = {}
    for (s, e) in _date_windows(start, end):
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={symbol},day,{s},{e},800,{adjust}")
        got: List[Row] = []
        # 空响应多为限流所致，对历史窗口退避重试（上市后区间不应为空）
        for attempt in range(4):
            d = _http_json(url)
            node = (d.get("data") or {}).get(symbol) or {}
            got = parse_tencent_kline(node)
            if got:
                break
            time.sleep(0.8 * (attempt + 1))
        for r in got:
            rows[r[0]] = r
        time.sleep(delay)
    return rows_to_frame([rows[k] for k in sorted(rows)])


def fetch_daily_sina(symbol: str, datalen: int = 1000) -> pd.DataFrame:
    """新浪源（回退）：取最近 datalen 个交易日日线。"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}")
    d = _http_json(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    return rows_to_frame(parse_sina_kline(d if isinstance(d, list) else []))


def fetch_daily(symbol: str, start: str = "2016-01-01", end: Optional[str] = None,
                adjust: str = "hfq", source: str = "auto") -> pd.DataFrame:
    """抓取单只 A 股日线。source: 'tencent' | 'sina' | 'auto'（先腾讯失败再新浪）。"""
    if source in ("tencent", "auto"):
        try:
            df = fetch_daily_tencent(symbol, start, end, adjust)
            if len(df) > 0:
                return df
        except Exception:
            if source == "tencent":
                raise
    return fetch_daily_sina(symbol)


def fetch_universe(symbols: Sequence[str], out_dir: str, start: str = "2016-01-01",
                   end: Optional[str] = None, adjust: str = "hfq",
                   delay: float = 0.3, min_rows: int = 200) -> Dict[str, int]:
    """抓取一篮子股票并存为 ``out_dir/<symbol>.csv``，返回 {symbol: rows}。"""
    os.makedirs(out_dir, exist_ok=True)
    result: Dict[str, int] = {}
    for sym in symbols:
        df = fetch_daily(sym, start, end, adjust)
        if len(df) < min_rows:
            result[sym] = len(df)
            continue
        df.to_csv(os.path.join(out_dir, f"{sym}.csv"))
        result[sym] = len(df)
        time.sleep(delay)
    return result


# ------------------------------------------------------------------ 本地数据集加载
def load_ashare_panel(data_dir: str, field: str = "close",
                      drop_incomplete: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """从本地 CSV 目录读出对齐的价格/成交量面板。

    返回 (prices, volumes)：index=交易日(DatetimeIndex)，columns=symbol。
    drop_incomplete=True 时裁掉「任一资产尚未上市」的早期行，使面板无 NaN（便于回测）。
    """
    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".csv"))
    prices: Dict[str, pd.Series] = {}
    volumes: Dict[str, pd.Series] = {}
    for f in files:
        sym = f[:-4]
        df = pd.read_csv(os.path.join(data_dir, f), parse_dates=["date"]).set_index("date").sort_index()
        prices[sym] = pd.to_numeric(df[field], errors="coerce")
        volumes[sym] = pd.to_numeric(df["volume"], errors="coerce")
    p = pd.DataFrame(prices)
    v = pd.DataFrame(volumes)
    # 非正价格视为无效(停牌记 0 等) -> NaN
    p = p.where(p > 0)
    # 先用历史 ffill 填充停牌缺口(仅用过去值，无未来函数)，再裁剪，避免首部无法填充
    p = p.ffill()
    v = v.fillna(0.0)
    if drop_incomplete:
        first_valid = p.apply(lambda s: s.first_valid_index()).max()
        p = p.loc[first_valid:]
        v = v.loc[first_valid:]
    return p, v


class TencentKlineSource(DataSource):
    """把腾讯行情包装成统一 ``DataSource`` 接口（load 时联网抓取）。"""

    def __init__(self, adjust: str = "hfq"):
        self.adjust = adjust

    def load(self, symbol: str, start=None, end=None) -> pd.DataFrame:
        s = pd.Timestamp(start).date().isoformat() if start is not None else "2016-01-01"
        e = pd.Timestamp(end).date().isoformat() if end is not None else None
        return fetch_daily_tencent(symbol, s, e, self.adjust)
