"""clean 模块测试：复权、日历重建+限量填充、异常值检测、去重排序。"""
import numpy as np
import pandas as pd
import pytest

from kairos_data import (
    adjust_prices,
    dedup_sort,
    detect_outliers,
    ffill_policy,
    reindex_calendar,
)


def _dates(n, start="2021-01-01"):
    return pd.date_range(start, periods=n, freq="B")


# ---- adjust_prices：前/后复权在给定因子下的数值正确 ----
def test_adjust_prices_forward_hfq_known_values():
    idx = _dates(3)
    df = pd.DataFrame({
        "open": [100.0, 100.0, 100.0],
        "high": [100.0, 100.0, 100.0],
        "low": [100.0, 100.0, 100.0],
        "close": [100.0, 100.0, 100.0],
        "volume": [10.0, 10.0, 10.0],
    }, index=idx)
    factors = pd.Series([1.0, 2.0, 4.0], index=idx)  # 基准日=1
    adj = adjust_prices(df, factors, mode="hfq")       # 后复权：raw * f
    # 后复权以最早为锚：[100*1, 100*2, 100*4]
    assert list(adj["close"]) == pytest.approx([100.0, 200.0, 400.0])
    # 成交量不复权
    assert list(adj["volume"]) == pytest.approx([10.0, 10.0, 10.0])


def test_adjust_prices_backward_qfq_known_values():
    idx = _dates(3)
    df = pd.DataFrame({"close": [100.0, 100.0, 100.0]}, index=idx)
    factors = pd.Series([1.0, 2.0, 4.0], index=idx)
    adj = adjust_prices(df, factors, mode="qfq")       # 前复权：raw * f / f_latest
    # f_latest = 4 -> [100*1/4, 100*2/4, 100*4/4] = [25, 50, 100]，最新日不变
    assert list(adj["close"]) == pytest.approx([25.0, 50.0, 100.0])


def test_adjust_prices_aliases_and_scalar():
    idx = _dates(2)
    df = pd.DataFrame({"close": [10.0, 20.0]}, index=idx)
    # 标量因子 = 对所有行同乘
    assert list(adjust_prices(df, 2.0, mode="forward")["close"]) == pytest.approx([20.0, 40.0])
    # 英文/中文别名等价
    a = adjust_prices(df, pd.Series([1.0, 2.0], index=idx), mode="backward")
    b = adjust_prices(df, pd.Series([1.0, 2.0], index=idx), mode="前复权")
    pd.testing.assert_frame_equal(a, b)


def test_adjust_prices_bad_mode_raises():
    idx = _dates(2)
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    with pytest.raises(ValueError):
        adjust_prices(df, pd.Series([1.0, 1.0], index=idx), mode="unknown")


# ---- reindex_calendar + ffill_policy：补齐缺失日并限量填充 ----
def test_reindex_calendar_fills_missing_dates():
    have = _dates(3)                       # 3 天
    full = pd.date_range(have[0], have[-1], freq="D")   # 含中间所有日历日（更多）
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=have)
    out = reindex_calendar(df, full)
    # 索引被重建为完整日历，长度增加，新增位置为 NaN
    assert len(out) == len(full)
    assert out["close"].isna().sum() == len(full) - 3


def test_ffill_policy_limits_consecutive_fills():
    idx = pd.date_range("2021-01-01", periods=6, freq="D")
    # 值 1.0 后跟 4 个 NaN，再一个值
    s = pd.DataFrame({"x": [1.0, np.nan, np.nan, np.nan, np.nan, 9.0]}, index=idx)
    filled = ffill_policy(s, limit=2)
    # 只填充前 2 个 NaN，其后 2 个仍为 NaN
    assert list(filled["x"].iloc[1:3]) == pytest.approx([1.0, 1.0])
    assert np.isnan(filled["x"].iloc[3])
    assert np.isnan(filled["x"].iloc[4])
    assert filled["x"].iloc[5] == 9.0


def test_reindex_then_ffill_pipeline_behavior():
    have = pd.to_datetime(["2021-01-01", "2021-01-04"])  # 缺中间两天
    df = pd.DataFrame({"close": [10.0, 40.0]}, index=have)
    cal = pd.date_range("2021-01-01", "2021-01-04", freq="D")
    out = ffill_policy(reindex_calendar(df, cal), limit=1)
    # 01-02 被填充为 10.0；01-03 超过 limit=1 仍 NaN；01-04 为原值 40.0
    assert out.loc["2021-01-02", "close"] == 10.0
    assert np.isnan(out.loc["2021-01-03", "close"])
    assert out.loc["2021-01-04", "close"] == 40.0


# ---- detect_outliers：能标出注入的极端点 ----
def test_detect_outliers_mad_flags_injected_spike():
    rng = np.random.default_rng(0)
    base = 100.0 + rng.standard_normal(200) * 0.5     # 平稳小幅波动
    s = pd.Series(base, index=_dates(200))
    spike_pos = 123
    s.iloc[spike_pos] = 500.0                          # 注入极端点
    mask = detect_outliers(s.to_frame("v"), method="mad", threshold=3.5)
    assert bool(mask["v"].iloc[spike_pos]) is True     # 极端点被标记
    # 绝大多数正常点不应被标记
    assert int(mask["v"].sum()) <= 5


def test_detect_outliers_rolling_flags_spike():
    idx = _dates(60)
    s = pd.Series(np.linspace(10, 12, 60), index=idx)
    s.iloc[40] = 200.0
    mask = detect_outliers(s, method="rolling", window=10, threshold=3.0)
    assert isinstance(mask, pd.Series)
    assert bool(mask.iloc[40]) is True


def test_detect_outliers_constant_column_no_false_positive():
    idx = _dates(20)
    df = pd.DataFrame({"c": [5.0] * 20}, index=idx)     # 常量列 MAD=0
    mask = detect_outliers(df, method="mad", threshold=3.0)
    assert int(mask["c"].sum()) == 0


# ---- dedup_sort ----
def test_dedup_sort_removes_dup_and_orders():
    idx = pd.to_datetime(["2021-01-03", "2021-01-01", "2021-01-01", "2021-01-02"])
    df = pd.DataFrame({"close": [3.0, 1.0, 1.5, 2.0]}, index=idx)
    out = dedup_sort(df, keep="last")
    assert list(out.index) == sorted(set(idx))
    # 重复的 01-01 保留最后一条（1.5）
    assert out.loc["2021-01-01", "close"] == 1.5
    assert out.index.is_monotonic_increasing
