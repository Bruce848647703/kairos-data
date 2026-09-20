"""Kairos Data 演示：合成 OHLCV → 存 DataStore → 读回 → 复权 → 对齐日历 → as-of 合并。

运行： python examples/demo.py
全程离线、固定 seed、结果可复现。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import kairos_data as kd
from kairos_data import (
    Bar,
    DataStore,
    Pipeline,
    SyntheticSource,
    adjust_prices,
    align,
    asof_merge,
    bars_to_frame,
    business_days,
    dedup_sort,
    detect_outliers,
    ffill_policy,
    frame_to_panel,
    reindex_calendar,
)

SYMBOLS = ["AAA", "BBB", "CCC"]


def _build_close_panel(src: SyntheticSource, symbols) -> pd.DataFrame:
    """把多只标的的合成行情收盘价拼成面板（index=日期, columns=symbol）。"""
    frames = []
    for s in symbols:
        df = src.load(s)
        frames.append(df[["close"]].rename(columns={"close": s}))
    return pd.concat(frames, axis=1)


def main() -> None:
    src = SyntheticSource(seed=7, start="2021-01-01", periods=260)

    print("=" * 64)
    print("① 合成 OHLCV（SyntheticSource，GBM，seed=7，离线可复现）")
    raw = src.load("AAA")
    print(raw.head(3).to_string())
    print(f"形状={raw.shape}；OHLC 关系合理(low<=open/close<=high)={kd.ohlc_is_consistent(raw)}")

    print("=" * 64)
    print("② 本地存储往返（DataStore，默认 CSV）")
    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(tmp, format="csv")
        store.save("AAA_raw", raw)
        loaded = store.load("AAA_raw")
        same_shape = loaded.shape == raw.shape
        close_match = np.allclose(loaded["close"].values, raw["close"].values)
        print(f"已存数据集: {store.list()}")
        print(f"往返一致: 形状={same_shape}, close 数值匹配={close_match}")

    print("=" * 64)
    print("③ 复权（adjust_prices）：后半段累计因子=2.0 的一次除权事件")
    half = len(raw) // 2
    factors = pd.Series(1.0, index=raw.index)
    factors.iloc[half:] = 2.0
    hfq = adjust_prices(raw, factors, mode="hfq")   # 后复权：adj = raw * f
    qfq = adjust_prices(raw, factors, mode="qfq")   # 前复权：adj = raw * f / f_latest
    print(f"原始   close[0]={raw['close'].iloc[0]:8.4f}  close[-1]={raw['close'].iloc[-1]:8.4f}")
    print(f"后复权 close[0]={hfq['close'].iloc[0]:8.4f} (×{factors.iloc[0]:.0f}, 锚定最早)")
    print(f"后复权 close[half]={hfq['close'].iloc[half]:8.4f} (×{factors.iloc[half]:.0f})")
    print(f"前复权 close[0]={qfq['close'].iloc[0]:8.4f} (×{factors.iloc[0]/factors.iloc[-1]:.2f}, 锚定最新)")
    print(f"前复权 close[-1]={qfq['close'].iloc[-1]:8.4f} (×{factors.iloc[-1]/factors.iloc[-1]:.0f}, 最新不变)")

    print("=" * 64)
    print("④ 对齐日历 + 限量前向填充（Pipeline：dedup_sort → reindex → ffill）")
    panel = _build_close_panel(src, SYMBOLS)
    gappy = panel.copy()
    gappy.loc[gappy.index[10:15], "BBB"] = np.nan   # 模拟 BBB 连续停牌/缺失
    full_cal = business_days(panel.index[0], panel.index[-1])
    pipe = (Pipeline()
            .add_step(dedup_sort)
            .add_step(reindex_calendar, full_cal)
            .add_step(ffill_policy, limit=3))
    cleaned = pipe.run(gappy)
    before_nan = int(gappy["BBB"].isna().sum())
    after_nan = int(cleaned["BBB"].isna().sum())
    print(f"管道: {pipe!r}")
    print(f"BBB 缺失数: 清洗前={before_nan} → 限量填充后={after_nan}（limit=3，超出部分仍留 NaN）")

    print("=" * 64)
    print("⑤ 异常值检测（detect_outliers，MAD 稳健 z）")
    spiked = panel["AAA"].copy()
    spike_pos = len(spiked) // 3
    spiked.iloc[spike_pos] = spiked.median() * 5.0   # 注入一个极端点
    mask = detect_outliers(spiked.to_frame("close"), method="mad", threshold=3.5)
    print(f"注入极端点位置={spike_pos}，是否被标记={bool(mask['close'].iloc[spike_pos])}")
    print(f"全序列被标记为异常的点共 {int(mask['close'].sum())} 个")

    print("=" * 64)
    print("⑥ 多标的对齐（calendar.align，inner 交集）")
    a = panel[["AAA"]].iloc[5:]
    b = panel[["BBB"]].iloc[:-5]
    aligned = align([a, b], how="inner")
    print(f"AAA 区间={a.index[0].date()}~{a.index[-1].date()} (行数 {len(a)})")
    print(f"BBB 区间={b.index[0].date()}~{b.index[-1].date()} (行数 {len(b)})")
    print(f"交集对齐后行数={len(aligned[0])}")

    print("=" * 64)
    print("⑦ 时点正确性合并（asof_merge，backward，杜绝未来函数）")
    event_dates = panel.index[[3, 20, 45, 120]]        # 不定期发布的基本面事件
    events = pd.DataFrame({"score": [0.5, -1.2, 0.8, 0.1]}, index=event_dates)
    daily = panel[["AAA"]].copy()
    merged = asof_merge(daily, events, direction="backward")
    print("每日行情 as-of 合并事件 score（每行只取 <= 当时的最近事件）：")
    print(merged.iloc[[2, 3, 19, 20, 44, 45]][["AAA", "score"]].to_string())
    nan_before = int(merged["score"].iloc[:3].isna().sum())
    print(f"首个事件(第3日)之前共 {nan_before} 行为 NaN（无未来值泄露）")

    print("=" * 64)
    print("⑧ 长表 → 面板（bars_to_frame + frame_to_panel）")
    bars = []
    for s in SYMBOLS:
        row = src.load(s).iloc[0]
        bars.append(Bar(s, row.name, row["open"], row["high"], row["low"], row["close"], row["volume"]))
    long_df = bars_to_frame(bars)
    close_panel = frame_to_panel(long_df, field="close")
    print(close_panel.to_string())

    print("\n演示完成 ✅（全程离线、固定 seed，可复现）")


if __name__ == "__main__":
    main()
