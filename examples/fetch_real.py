"""抓取真实 A 股日线数据（腾讯/新浪公开行情）到 data/ashare/。

运行（需联网）： python examples/fetch_real.py
默认抓取 universe.LIQUID_A_SHARES 全部成分的后复权(hfq)日线。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kairos_data import ashare, universe


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "data", "ashare")
    syms = universe.symbols()
    print(f"抓取 {len(syms)} 只 A 股后复权(hfq)日线 -> {out}")
    res = ashare.fetch_universe(syms, out, start="2016-01-01", adjust="hfq", delay=0.3)
    ok = {k: v for k, v in res.items() if v >= 200}
    print(f"成功 {len(ok)}/{len(syms)}；总行数 {sum(ok.values())}")
    for s, n in list(ok.items())[:5]:
        print(f"  {s} {universe.name_of(s)}: {n} 行")
    prices, _ = ashare.load_ashare_panel(out)
    print(f"对齐面板: {prices.shape[0]} 交易日 × {prices.shape[1]} 资产，"
          f"区间 {prices.index[0].date()} ~ {prices.index[-1].date()}")


if __name__ == "__main__":
    main()
