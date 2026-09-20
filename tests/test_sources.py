"""sources 模块测试：SyntheticSource 确定性与 OHLC 合理性，CSVSource 往返。"""
import numpy as np
import pandas as pd
import pytest

from kairos_data import CSVSource, SyntheticSource, ohlc_is_consistent
from kairos_data.sources import ParquetSource, _pyarrow_available


# ---- SyntheticSource：同 seed 两次一致 ----
def test_synthetic_same_seed_is_deterministic():
    a = SyntheticSource(seed=123, start="2020-01-01", periods=100).load("AAA")
    b = SyntheticSource(seed=123, start="2020-01-01", periods=100).load("AAA")
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_synthetic_repeat_call_on_same_instance_stable():
    src = SyntheticSource(seed=5, periods=50)
    a = src.load("XYZ")
    b = src.load("XYZ")           # 再次调用同实例、同 symbol
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_synthetic_different_seed_differs():
    a = SyntheticSource(seed=1, periods=80).load("AAA")
    b = SyntheticSource(seed=2, periods=80).load("AAA")
    assert not np.allclose(a["close"].values, b["close"].values)


def test_synthetic_symbol_entropy_independent_of_call_order():
    src = SyntheticSource(seed=9, periods=60)
    # 先加载 BBB 再加载 AAA，AAA 结果应与单独加载 AAA 相同（symbol 派生熵，与顺序无关）
    _ = src.load("BBB")
    aaa_after = src.load("AAA")
    aaa_solo = SyntheticSource(seed=9, periods=60).load("AAA")
    pd.testing.assert_frame_equal(aaa_after, aaa_solo, check_exact=True)
    # 不同 symbol 应产生不同序列
    assert not np.allclose(aaa_solo["close"].values, _["close"].values)


# ---- SyntheticSource：OHLC 关系合理 low<=open/close<=high ----
def test_synthetic_ohlc_relationship_holds():
    df = SyntheticSource(seed=7, periods=300).load("AAA")
    assert ohlc_is_consistent(df)
    assert (df["low"] <= df["open"] + 1e-12).all()
    assert (df["low"] <= df["close"] + 1e-12).all()
    assert (df["open"] <= df["high"] + 1e-12).all()
    assert (df["close"] <= df["high"] + 1e-12).all()
    assert (df["low"] > 0).all()
    assert (df["volume"] > 0).all()


def test_synthetic_columns_and_index():
    df = SyntheticSource(seed=3, periods=10).load("AAA")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)


def test_synthetic_respects_start_end_window():
    df = SyntheticSource(seed=3).load("AAA", start="2021-06-01", end="2021-06-30")
    assert df.index.min() >= pd.Timestamp("2021-06-01")
    assert df.index.max() <= pd.Timestamp("2021-06-30")


# ---- CSVSource：写盘后按目录读取往返 ----
def test_csv_source_roundtrip(tmp_path):
    src = SyntheticSource(seed=11, periods=30)
    df = src.load("AAA")
    path = tmp_path / "AAA.csv"
    df.to_csv(path)
    loaded = CSVSource(str(tmp_path)).load("AAA")
    pd.testing.assert_frame_equal(loaded, df, check_exact=True, check_freq=False)


def test_csv_source_slicing_and_symbols(tmp_path):
    df = SyntheticSource(seed=11, periods=40).load("AAA")
    df.to_csv(tmp_path / "AAA.csv")
    SyntheticSource(seed=11, periods=40).load("BBB").to_csv(tmp_path / "BBB.csv")
    src = CSVSource(str(tmp_path))
    assert set(src.symbols()) == {"AAA", "BBB"}
    sub = src.load("AAA", start=df.index[5], end=df.index[10])
    assert sub.index.min() >= df.index[5]
    assert sub.index.max() <= df.index[10]


def test_csv_source_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        CSVSource(str(tmp_path)).load("NOPE")


def test_parquet_source_clear_error_when_missing(monkeypatch):
    # 模拟缺失 pyarrow：ParquetSource 构造应给出清晰 ImportError
    import kairos_data.sources as sources_mod
    monkeypatch.setattr(sources_mod, "_pyarrow_available", lambda: False)
    with pytest.raises(ImportError):
        ParquetSource(root="whatever")


@pytest.mark.skipif(not _pyarrow_available(), reason="pyarrow 未安装")
def test_parquet_source_roundtrip_when_available(tmp_path):
    df = SyntheticSource(seed=13, periods=20).load("AAA")
    df.to_parquet(tmp_path / "AAA.parquet")
    loaded = ParquetSource(str(tmp_path)).load("AAA")
    pd.testing.assert_frame_equal(loaded.sort_index(axis=1), df.sort_index(axis=1),
                                  check_freq=False)
