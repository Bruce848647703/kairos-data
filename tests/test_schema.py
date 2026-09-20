"""schema 模块测试：Bar/Candle、bars_to_frame、frame_to_panel、ohlc 校验。"""
import pandas as pd
import pytest

from kairos_data import (
    Bar,
    Candle,
    bars_to_frame,
    empty_panel,
    frame_to_panel,
    ohlc_is_consistent,
)


def test_bar_is_frozen_and_hashable():
    b = Bar("AAA", "2021-01-01", 10.0, 11.0, 9.0, 10.5, 1000.0)
    # frozen dataclass 不可修改
    with pytest.raises(Exception):
        b.close = 1.0
    # 可哈希（能进 set）
    assert len({b, Bar("AAA", "2021-01-01", 10.0, 11.0, 9.0, 10.5, 1000.0)}) == 1


def test_bar_normalizes_datetime_and_floats():
    b = Bar("AAA", "2021-01-01", 10, 11, 9, 10.5, 1000)
    assert isinstance(b.datetime, pd.Timestamp)
    assert isinstance(b.open, float)


def test_bar_is_valid_ohlc():
    good = Bar("A", "2021-01-01", 10.0, 11.0, 9.0, 10.5)
    bad_high = Bar("A", "2021-01-01", 10.0, 9.5, 9.0, 10.5)   # close > high
    bad_low = Bar("A", "2021-01-01", 10.0, 11.0, 10.2, 10.5)  # open < low
    assert good.is_valid() is True
    assert bad_high.is_valid() is False
    assert bad_low.is_valid() is False


def test_candle_is_alias_of_bar():
    assert Candle is Bar


def test_typical_price():
    b = Bar("A", "2021-01-01", 10.0, 12.0, 9.0, 11.0)
    assert b.typical_price() == pytest.approx((12.0 + 9.0 + 11.0) / 3.0)


def test_bars_to_frame_shape_and_index():
    bars = [
        Bar("AAA", "2021-01-02", 2, 3, 1, 2.5, 200),
        Bar("AAA", "2021-01-01", 1, 2, 0.5, 1.5, 100),
    ]
    df = bars_to_frame(bars)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing           # 已按时间排序
    assert list(df.columns[:2]) == ["symbol", "open"]
    assert df.iloc[0]["symbol"] == "AAA"


def test_bars_to_frame_empty():
    df = bars_to_frame([])
    assert df.empty
    assert "close" in df.columns


def test_frame_to_panel_pivot():
    idx = pd.to_datetime(["2021-01-01", "2021-01-01", "2021-01-02", "2021-01-02"])
    long_df = pd.DataFrame({
        "symbol": ["AAA", "BBB", "AAA", "BBB"],
        "close": [1.0, 2.0, 3.0, 4.0],
    }, index=idx)
    panel = frame_to_panel(long_df, field="close")
    assert list(panel.columns) == ["AAA", "BBB"]
    assert panel.loc["2021-01-01", "AAA"] == 1.0
    assert panel.loc["2021-01-02", "BBB"] == 4.0


def test_empty_panel_fill():
    p = empty_panel(pd.date_range("2021-01-01", periods=3), ["A", "B"], fill=0.0)
    assert p.shape == (3, 2)
    assert (p.values == 0.0).all()


def test_ohlc_is_consistent_true_and_false():
    idx = pd.date_range("2021-01-01", periods=2, freq="D")
    good = pd.DataFrame({
        "open": [10.0, 11.0], "high": [12.0, 13.0],
        "low": [9.0, 10.0], "close": [11.0, 12.0],
    }, index=idx)
    bad = good.copy()
    bad.loc[bad.index[1], "high"] = 5.0   # high < low，破坏一致性
    assert ohlc_is_consistent(good) is True
    assert ohlc_is_consistent(bad) is False
