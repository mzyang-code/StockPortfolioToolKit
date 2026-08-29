"""示例：从价格面板生成 MOM / STR / WSTR 因子信号文件。

本包只消费 alpha，不生成信号。若需要 Jiang-Kelly-Xiu (2023) 的三个价格类
对照因子，用本脚本先算好落盘，再在 input.json 的 signals 里各列一项即可。

    python examples/build_jkx_factors.py \
        --prices /path/to/prices.feather --out-dir /path/to/signals

注意：本脚本是最小演示，只产出 alpha 列，实现收益交给 engine 用 close 计算。若价格面板
的 close 未做拆股复权，多空腿会被假收益污染。生产口径见 examples/{mom,str,wstr}/ —— 那里
的信号表额外带一列复权 fwd_ret，配 engine 的 forward_return.source="signals" 使用。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

LAGS = {"MOM": (252, 21), "STR": (21, 0), "WSTR": (5, 0)}


def build(prices: pd.DataFrame, date_col: str, id_col: str, close_col: str) -> dict:
    panel = prices.sort_values([id_col, date_col]).reset_index(drop=True)
    closes = panel.groupby(id_col, sort=False)[close_col]
    lagged = {lag: closes.shift(lag) for lag in (5, 21, 252)}
    lagged[0] = panel[close_col]

    factors = {}
    # MOM 取 12-2 动量，两个反转因子取负号，全部使用简单收益
    factors["MOM"] = lagged[21] / lagged[252] - 1.0
    factors["STR"] = -(lagged[0] / lagged[21] - 1.0)
    factors["WSTR"] = -(lagged[0] / lagged[5] - 1.0)
    return {
        name: panel[[date_col, id_col]].assign(alpha=values).dropna(subset=["alpha"])
        for name, values in factors.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 JKX 对照因子信号文件")
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--date-col", default="date")
    parser.add_argument("--id-col", default="id")
    parser.add_argument("--close-col", default="close")
    args = parser.parse_args()

    prices = pd.read_feather(args.prices, columns=[args.date_col, args.id_col, args.close_col])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in build(prices, args.date_col, args.id_col, args.close_col).items():
        path = args.out_dir / f"signal_{name.lower()}.feather"
        frame.reset_index(drop=True).to_feather(path)
        print(f"{name}: {len(frame):,} rows -> {path}")


if __name__ == "__main__":
    main()
