"""pipeline 模块测试：多步管道与逐步手工调用结果一致。"""
import numpy as np
import pandas as pd
import pytest

from kairos_data import Pipeline, Step, business_days, dedup_sort, ffill_policy, reindex_calendar


def _messy_frame():
    # 含乱序、重复索引、缺失日的原始数据
    idx = pd.to_datetime([
        "2021-01-04", "2021-01-01", "2021-01-01", "2021-01-05", "2021-01-07",
    ])
    return pd.DataFrame({"close": [4.0, 1.0, 1.5, 5.0, np.nan]}, index=idx)


def test_pipeline_matches_manual_sequential_calls():
    df = _messy_frame()
    cal = business_days("2021-01-01", "2021-01-08")

    pipe = (Pipeline()
            .add_step(dedup_sort)
            .add_step(reindex_calendar, cal)
            .add_step(ffill_policy, limit=1))
    via_pipe = pipe.run(df)

    # 逐步手工调用（完全相同的顺序与参数）
    step1 = dedup_sort(df)
    step2 = reindex_calendar(step1, cal)
    manual = ffill_policy(step2, limit=1)

    pd.testing.assert_frame_equal(via_pipe, manual, check_exact=True)


def test_pipeline_transform_alias_equals_run():
    df = _messy_frame()
    cal = business_days("2021-01-01", "2021-01-08")
    pipe = Pipeline([dedup_sort, Step(reindex_calendar, args=(cal,))])
    pd.testing.assert_frame_equal(pipe.run(df), pipe.transform(df))


def test_pipeline_order_matters():
    df = pd.DataFrame({"x": [3.0, 1.0, 2.0]},
                      index=pd.to_datetime(["2021-01-03", "2021-01-01", "2021-01-02"]))
    asc = Pipeline().add_step(lambda d: d.sort_index()).run(df)
    assert list(asc.index) == sorted(df.index)


def test_pipeline_passes_kwargs_and_name():
    pipe = Pipeline().add_step(ffill_policy, limit=2, name="fill")
    assert len(pipe) == 1
    assert pipe.steps[0].label() == "fill"
    assert "fill" in repr(pipe)


def test_pipeline_add_step_rejects_non_callable():
    with pytest.raises(TypeError):
        Pipeline().add_step(123)


def test_pipeline_step_call_applies_args():
    idx = pd.date_range("2021-01-01", periods=3, freq="D")
    df = pd.DataFrame({"x": [1.0, np.nan, np.nan]}, index=idx)
    step = Step(ffill_policy, kwargs={"limit": 1})
    out = step(df)
    assert out["x"].iloc[1] == 1.0
    assert np.isnan(out["x"].iloc[2])   # 超过 limit=1 仍 NaN
