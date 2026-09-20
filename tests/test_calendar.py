"""calendar 模块测试：business_days、align、as_of。"""
import numpy as np
import pandas as pd
import pytest

from kairos_data import align, as_of, as_of_row, business_days


def test_business_days_by_end_excludes_weekend():
    idx = business_days("2021-01-01", "2021-01-10")
    # 2021-01-02/03 为周末，应被排除
    assert pd.Timestamp("2021-01-02") not in idx
    assert pd.Timestamp("2021-01-04") in idx


def test_business_days_by_periods():
    idx = business_days("2021-01-01", periods=5)
    assert len(idx) == 5


def test_business_days_removes_holidays():
    idx = business_days("2021-01-01", "2021-01-10",
                        holidays=["2021-01-04", "2021-01-05"])
    assert pd.Timestamp("2021-01-04") not in idx
    assert pd.Timestamp("2021-01-05") not in idx


def test_business_days_requires_end_or_periods():
    with pytest.raises(ValueError):
        business_days("2021-01-01")


def test_align_inner_intersection():
    idx_a = pd.date_range("2021-01-01", periods=5, freq="D")
    idx_b = pd.date_range("2021-01-03", periods=5, freq="D")
    a = pd.DataFrame({"A": np.arange(5.0)}, index=idx_a)
    b = pd.DataFrame({"B": np.arange(5.0)}, index=idx_b)
    out = align([a, b], how="inner")
    common = idx_a.intersection(idx_b)
    assert len(out[0]) == len(common)
    assert out[0].index.equals(out[1].index)


def test_align_outer_union_fills_nan():
    idx_a = pd.date_range("2021-01-01", periods=3, freq="D")
    idx_b = pd.date_range("2021-01-03", periods=3, freq="D")
    a = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx_a)
    b = pd.DataFrame({"B": [10.0, 20.0, 30.0]}, index=idx_b)
    out = align([a, b], how="outer")
    union = idx_a.union(idx_b).sort_values()
    assert len(out[0]) == len(union)
    # 01-01 处 B 尚未出现 -> NaN
    assert np.isnan(out[1]["B"].iloc[0])


def test_as_of_row_returns_latest_known():
    idx = pd.date_range("2021-01-01", periods=5, freq="D")
    df = pd.DataFrame({"v": np.arange(5.0)}, index=idx)
    row = as_of_row(df, "2021-01-03 12:00")
    assert row.name == pd.Timestamp("2021-01-03")
    assert row["v"] == 2.0


def test_as_of_row_before_start_is_none():
    idx = pd.date_range("2021-01-05", periods=3, freq="D")
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0]}, index=idx)
    assert as_of_row(df, "2021-01-01") is None


def test_align_empty_returns_empty():
    assert align([]) == []
