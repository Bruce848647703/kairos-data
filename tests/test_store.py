"""store 模块测试：DataStore CSV 往返一致、list/exists、parquet 缺失回退。"""
import pandas as pd
import pytest

import kairos_data.store as store_mod
from kairos_data import DataStore


def _sample_frame():
    idx = pd.date_range("2021-01-01", periods=5, freq="D")
    idx.name = "datetime"
    return pd.DataFrame({
        "open": [1.0, 2.0, 3.0, 4.0, 5.0],
        "high": [1.5, 2.5, 3.5, 4.5, 5.5],
        "low": [0.5, 1.5, 2.5, 3.5, 4.5],
        "close": [1.123456789, 2.0, 3.0, 4.0, 5.0],
        "volume": [100.0, 200.0, 300.0, 400.0, 500.0],
    }, index=idx)


def test_save_load_csv_roundtrip_exact(tmp_path):
    store = DataStore(str(tmp_path), format="csv")
    df = _sample_frame()
    store.save("AAA", df)
    loaded = store.load("AAA")
    # 逐位一致（含索引名、列 dtype、浮点精度）；CSV 不保留 index.freq，故忽略 freq
    pd.testing.assert_frame_equal(loaded, df, check_exact=True, check_freq=False)


def test_exists_and_list(tmp_path):
    store = DataStore(str(tmp_path))
    assert store.exists("X") is False
    store.save("X", _sample_frame())
    store.save("Y", _sample_frame())
    assert store.exists("X") is True
    assert store.list() == ["X", "Y"]


def test_load_missing_raises(tmp_path):
    store = DataStore(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        store.load("nope")


def test_save_rejects_non_dataframe(tmp_path):
    store = DataStore(str(tmp_path))
    with pytest.raises(TypeError):
        store.save("bad", [1, 2, 3])


def test_default_format_is_csv(tmp_path):
    store = DataStore(str(tmp_path))
    assert store.format == "csv"
    path = store.save("D", _sample_frame())
    assert path.endswith(".csv")


def test_bad_format_raises(tmp_path):
    with pytest.raises(ValueError):
        DataStore(str(tmp_path), format="hdf5")


def test_parquet_falls_back_to_csv_when_pyarrow_missing(tmp_path, monkeypatch):
    # 模拟环境缺失 pyarrow：DataStore 应回退 CSV 并告警
    monkeypatch.setattr(store_mod, "_pyarrow_available", lambda: False)
    with pytest.warns(RuntimeWarning):
        store = DataStore(str(tmp_path), format="parquet")
    assert store.format == "csv"
    df = _sample_frame()
    path = store.save("Z", df)
    assert path.endswith(".csv")
    pd.testing.assert_frame_equal(store.load("Z"), df, check_exact=True, check_freq=False)


@pytest.mark.skipif(not store_mod._pyarrow_available(),
                    reason="pyarrow 未安装，跳过 parquet 可选路径")
def test_parquet_roundtrip_when_available(tmp_path):
    # 可选路径：pyarrow 存在时 parquet 也应正确往返（测试不依赖 parquet）
    store = DataStore(str(tmp_path), format="parquet")
    assert store.format == "parquet"
    df = _sample_frame()
    store.save("P", df)
    loaded = store.load("P")
    pd.testing.assert_frame_equal(loaded.sort_index(axis=1), df.sort_index(axis=1),
                                  check_freq=False)
