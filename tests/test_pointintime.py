"""pointintime 模块测试：asof_merge / lag 不引入未来数据。"""
import numpy as np
import pandas as pd
import pytest

from kairos_data import as_of, asof_merge, lag


def _idx(dates):
    return pd.DatetimeIndex(pd.to_datetime(dates))


# ---- asof_merge：某时点只拿到 <= 当时的值 ----
def test_asof_merge_backward_uses_only_known_values():
    left = pd.DataFrame({"px": [1.0, 2.0, 3.0, 4.0]},
                        index=_idx(["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04"]))
    # right 只在 01-01 与 01-03 发布值
    right = pd.DataFrame({"score": [10.0, 30.0]},
                         index=_idx(["2021-01-01", "2021-01-03"]))
    merged = asof_merge(left, right, direction="backward")
    got = list(merged["score"])
    # 01-02 只能看到 01-01 的 10（看不到 01-03 的 30，那是未来）
    assert got == pytest.approx([10.0, 10.0, 30.0, 30.0])


def test_asof_merge_no_leak_before_first_event():
    left = pd.DataFrame({"px": [1.0, 2.0, 3.0]},
                        index=_idx(["2021-01-01", "2021-01-02", "2021-01-03"]))
    right = pd.DataFrame({"score": [99.0]}, index=_idx(["2021-01-03"]))
    merged = asof_merge(left, right, direction="backward")
    # 01-03 之前没有任何已知事件 -> NaN，绝不提前看到 99
    assert np.isnan(merged["score"].iloc[0])
    assert np.isnan(merged["score"].iloc[1])
    assert merged["score"].iloc[2] == 99.0


def test_asof_merge_tolerance_respected():
    left = pd.DataFrame({"px": [1.0, 2.0]},
                        index=_idx(["2021-01-05", "2021-01-10"]))
    right = pd.DataFrame({"score": [7.0]}, index=_idx(["2021-01-01"]))
    merged = asof_merge(left, right, direction="backward", tolerance=pd.Timedelta("1D"))
    # 距离超过 1 天容差 -> 不匹配，均为 NaN
    assert merged["score"].isna().all()


def test_asof_merge_with_group_by():
    left = pd.DataFrame({
        "sym": ["A", "A", "B", "B"],
        "px": [1.0, 2.0, 3.0, 4.0],
    }, index=_idx(["2021-01-01", "2021-01-03", "2021-01-01", "2021-01-03"]))
    right = pd.DataFrame({
        "sym": ["A", "B"],
        "score": [100.0, 200.0],
    }, index=_idx(["2021-01-01", "2021-01-01"]))
    merged = asof_merge(left, right, by="sym", direction="backward")
    # A 组拿到 100，B 组拿到 200，互不串组
    assert list(merged["score"]) == pytest.approx([100.0, 100.0, 200.0, 200.0])


def test_asof_merge_column_key_form():
    left = pd.DataFrame({"t": _idx(["2021-01-01", "2021-01-04"]), "px": [1.0, 2.0]})
    right = pd.DataFrame({"t": _idx(["2021-01-02"]), "score": [5.0]})
    merged = asof_merge(left, right, on="t", direction="backward")
    # 01-01 早于唯一事件(01-02) -> NaN；01-04 取到 5
    assert np.isnan(merged["score"].iloc[0])
    assert merged["score"].iloc[1] == 5.0


# ---- lag：滞后 n 期只用过去 ----
def test_lag_shifts_values_no_future():
    idx = _idx(["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04"])
    s = pd.Series([10.0, 20.0, 30.0, 40.0], index=idx)
    out = lag(s, 1)
    # t 时刻得到 t-1 的值，首期为 NaN
    assert np.isnan(out.iloc[0])
    assert list(out.iloc[1:]) == pytest.approx([10.0, 20.0, 30.0])


def test_lag_dataframe_multi():
    idx = _idx(pd.date_range("2021-01-01", periods=5, freq="D"))
    df = pd.DataFrame({"a": np.arange(5.0), "b": np.arange(5.0) * 2}, index=idx)
    out = lag(df, 2)
    assert out["a"].isna().sum() == 2
    assert out["a"].iloc[2] == 0.0
    assert out["a"].iloc[4] == 2.0


def test_as_of_label_is_pit_safe():
    idx = _idx(["2021-01-01", "2021-01-05", "2021-01-10"])
    # 查询 01-07：应定位到 <= 它的最近时点 01-05，而非未来的 01-10
    assert as_of(idx, "2021-01-07") == pd.Timestamp("2021-01-05")
    # 查询早于全部 -> None
    assert as_of(idx, "2020-12-01") is None
    # 命中边界
    assert as_of(idx, "2021-01-05") == pd.Timestamp("2021-01-05")
