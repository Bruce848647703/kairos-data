"""kairos_data.ashare 的离线测试：只测纯解析器/本地加载，不联网。"""
import os

import numpy as np
import pandas as pd
import pytest

from kairos_data import ashare, universe


# 腾讯节点样例（行格式: [date, open, close, high, low, volume]）
TENCENT_NODE = {
    "qfqday": [
        ["2024-01-02", "100.0", "102.0", "103.0", "99.0", "10000"],
        ["2024-01-03", "102.0", "101.0", "104.0", "100.5", "12000"],
        ["bad-row"],  # 应被跳过
        ["2024-01-04", "101.0", "x", "105.0", "100.0", "9000"],  # 非法数值应被跳过
    ]
}
SINA_ARR = [
    {"day": "2024-01-02", "open": "100.0", "high": "103.0", "low": "99.0", "close": "102.0", "volume": "10000"},
    {"day": "2024-01-03", "open": "102.0", "high": "104.0", "low": "100.5", "close": "101.0", "volume": "12000"},
    {"garbage": True},
]


def test_parse_tencent():
    rows = ashare.parse_tencent_kline(TENCENT_NODE)
    assert len(rows) == 2  # 两条合法行
    d, o, h, l, c, v = rows[0]
    assert (d, o, h, l, c, v) == ("2024-01-02", 100.0, 103.0, 99.0, 102.0, 10000.0)


def test_parse_tencent_day_key_fallback():
    node = {"day": [["2024-01-02", "10", "11", "12", "9", "100"]]}
    rows = ashare.parse_tencent_kline(node)
    assert rows[0][1:] == (10.0, 12.0, 9.0, 11.0, 100.0)


def test_parse_sina():
    rows = ashare.parse_sina_kline(SINA_ARR)
    assert len(rows) == 2
    assert rows[0] == ("2024-01-02", 100.0, 103.0, 99.0, 102.0, 10000.0)


def test_rows_to_frame_schema_and_order():
    rows = ashare.parse_tencent_kline(TENCENT_NODE)
    df = ashare.rows_to_frame(rows)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing
    # OHLC 自洽
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()


def test_rows_to_frame_dedup():
    rows = [("2024-01-02", 1, 2, 0.5, 1.5, 10), ("2024-01-02", 1, 2, 0.5, 1.6, 11)]
    df = ashare.rows_to_frame(rows)
    assert len(df) == 1  # 去重


def test_rows_to_frame_empty():
    df = ashare.rows_to_frame([])
    assert df.empty and list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_load_ashare_panel(tmp_path):
    d = tmp_path / "ashare"
    d.mkdir()
    idx = pd.bdate_range("2024-01-01", periods=5)
    for sym, base in (("sh600000", 10.0), ("sz000001", 20.0)):
        pd.DataFrame({
            "date": idx, "open": base, "high": base + 1, "low": base - 1,
            "close": np.linspace(base, base + 2, 5), "volume": 1000.0,
        }).to_csv(d / f"{sym}.csv", index=False)
    prices, volumes = ashare.load_ashare_panel(str(d))
    assert list(prices.columns) == ["sh600000", "sz000001"]
    assert prices.shape == (5, 2) and volumes.shape == (5, 2)
    assert not prices.isna().any().any()


def test_load_ashare_panel_drop_incomplete(tmp_path):
    d = tmp_path / "ashare"
    d.mkdir()
    idx = pd.bdate_range("2024-01-01", periods=6)
    # A 全程上市；B 前 2 天未上市(NaN)
    a = pd.DataFrame({"date": idx, "open": 10, "high": 11, "low": 9,
                      "close": np.arange(6) + 10.0, "volume": 100})
    b = pd.DataFrame({"date": idx, "open": [np.nan, np.nan, 20, 20, 20, 20],
                      "high": [np.nan, np.nan, 21, 21, 21, 21], "low": [np.nan, np.nan, 19, 19, 19, 19],
                      "close": [np.nan, np.nan, 20, 21, 22, 23], "volume": [np.nan, np.nan, 100, 100, 100, 100]})
    a.to_csv(d / "sh600000.csv", index=False)
    b.to_csv(d / "sz000001.csv", index=False)
    prices, _ = ashare.load_ashare_panel(str(d), drop_incomplete=True)
    assert len(prices) == 4  # 裁掉前 2 行(任一资产未上市)
    assert not prices.isna().any().any()


def test_universe_wellformed():
    syms = universe.symbols()
    assert len(syms) == len(set(syms))
    for s in syms:
        assert s[:2] in ("sh", "sz") and s[2:].isdigit() and len(s[2:]) == 6
    # 行业分组的 symbol 都在总池里
    for sector, members in universe.SECTORS.items():
        for m in members:
            assert m in universe.LIQUID_A_SHARES, f"{sector}/{m} 不在池中"


def test_committed_dataset_present_and_clean():
    """已提交的真实数据集应存在且基本干净（若数据集被移除则跳过）。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(here, "data", "ashare")
    csvs = [f for f in os.listdir(data_dir) if f.endswith(".csv")] if os.path.isdir(data_dir) else []
    if not csvs:
        pytest.skip("未提交真实数据集")
    prices, volumes = ashare.load_ashare_panel(data_dir)
    assert prices.shape[1] == len(csvs)
    assert (prices.values > 0).all()
    assert not prices.isna().any().any()
    assert len(prices) > 500  # 至少数年真实日线
