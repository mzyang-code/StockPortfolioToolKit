"""WSTR（1 周超短期反转）信号生成：全量美股价格面板 → 含 alpha / fwd_ret 列的信号表。

口径与 stock_rag_v1 完全对齐，因子与收益分走两个价格口径：

  因子值   原始 close（未复权）—— 同 Portfolio/benchmarks.py:75-80
      WSTR = -(close[t] / close[t-5] - 1)      取负号，过去 1 周跌得多的排高分位

  前视收益 复权总收益（含分红）—— 同 Data/recompute_labels.py:87-88
      fwd_ret = exp(cum_log_ret[t+H] - cum_log_ret[t]) - 1

为什么收益必须复权：processed_stock_data.feather 的 close 是未复权原始价，缩股/拆股
会让 close 跳变（实测 id=22602 在 2023-12 反向缩股 1:100，close 口径算出 +25931% 的
假收益，复权口径 +160.3%）。旧项目早期也用过 price-only 口径，后来专门改成复权并把旧值
备份为 ret_fwd_price_old。因子值则保持原始 close，与 benchmarks.py 逐字一致。

全部简单收益，不用对数收益。lag 按「个股自身的交易行」位移（groupby(id).shift(k)）。

⚠ fwd_ret 的持有期在生成时就写死了，必须与 configs/engine.json 的 holding_days 一致；
  改持有期要同时改这里的 --holding-days 并重跑本脚本。

    python build_signal.py                      # 默认参数
    python build_signal.py --stride 5 --holding-days 5 --first-rebalance 2021-01-04
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.feather as feather

# ===== 默认参数（与 configs/*.json 保持同步） =====
# 两个路径是占位符，需与 configs/input.json 的 vars.CACHE / vars.SIGNALS 指向同一位置。
# 也可在命令行用 --prices / --out 覆盖，无需改动本文件。
PRICES_PATH = "/path/to/stock_rag_cache/processed/processed_stock_data.feather"
OUT_PATH = "/path/to/portfolio_tool_cache/signals/signal_wstr.feather"
FIRST_REBALANCE = "2021-01-04"
STRIDE = 5           # 调仓间隔（交易日），信号只在调仓日落盘
HOLDING_DAYS = 5     # 前视收益持有期，必须等于 engine.json 的 holding_days
LAG = 5              # 1 周反转窗口


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# 交易日历取自价格面板本身，起点是首个 >= first_rebalance 的交易日
def build_anchor_dates(
    trading_days: pd.DatetimeIndex, first_rebalance: str, stride: int
) -> pd.DatetimeIndex:
    start = pd.Timestamp(first_rebalance)
    future = trading_days[trading_days >= start]
    if len(future) == 0:
        raise SystemExit(f"价格面板中没有 >= {first_rebalance} 的交易日")
    if future[0] != start:
        log(f"  注意: {first_rebalance} 非交易日，起点顺延至 {future[0].date()}")
    return future[::stride]


def build_signal(
    prices_path: str, first_rebalance: str, stride: int, holding_days: int, lag: int
) -> pd.DataFrame:
    t0 = time.time()
    # 10.7 GB 面板只取四列 + memory-map，实测 <3s
    panel = feather.read_table(
        prices_path, columns=["date", "id", "close", "cum_log_ret"], memory_map=True
    ).to_pandas()
    log(f"读入价格面板 {len(panel):,} 行 / {panel['id'].nunique():,} 只 ({time.time() - t0:.1f}s)")

    trading_days = pd.DatetimeIndex(np.unique(panel["date"].to_numpy()))
    anchors = build_anchor_dates(trading_days, first_rebalance, stride)
    log(
        f"调仓日历 {len(anchors)} 期 | {anchors[0].date()} → {anchors[-1].date()} "
        f"| stride={stride} 交易日"
    )

    # lag 位移要求组内按日期升序；面板来源不保证有序，统一排一次
    panel = panel.sort_values(["id", "date"], kind="stable", ignore_index=True)
    grouped = panel.groupby("id", sort=False)

    # 因子：原始 close，反转取负号 —— 过去一段跌得越多，alpha 越高
    alpha = -(panel["close"] / grouped["close"].shift(lag) - 1.0)
    # 收益：复权口径，等价于 prod(1 + 日收益) - 1，天然免疫拆股与除息
    fwd_ret = np.exp(grouped["cum_log_ret"].shift(-holding_days) - panel["cum_log_ret"]) - 1.0

    out = panel[["date", "id"]].copy()
    out["alpha"] = alpha.to_numpy()
    out["fwd_ret"] = fwd_ret.to_numpy()

    # 先切调仓日再清洗，避免在 5000 万行上做无用功
    out = out[out["date"].isin(set(anchors))]
    out[["alpha", "fwd_ret"]] = out[["alpha", "fwd_ret"]].replace([np.inf, -np.inf], np.nan)
    # 只按 alpha 清洗；末尾几期没有 fwd_ret 属正常，交给 Engine 对齐时丢弃
    out = out.dropna(subset=["alpha"])
    return out.sort_values(["date", "id"], kind="stable", ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 WSTR(1 周反转) 信号表")
    parser.add_argument("--prices", default=PRICES_PATH)
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--first-rebalance", default=FIRST_REBALANCE)
    parser.add_argument("--stride", type=int, default=STRIDE)
    parser.add_argument("--holding-days", type=int, default=HOLDING_DAYS)
    parser.add_argument("--lag", type=int, default=LAG)
    args = parser.parse_args()

    log(f"WSTR 信号生成开始 | lag={args.lag} | 持有期 {args.holding_days} 日")
    signal = build_signal(
        args.prices, args.first_rebalance, args.stride, args.holding_days, args.lag
    )
    if signal.empty:
        raise SystemExit("信号表为空，检查回看窗口与调仓起点是否落在数据区间内")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    signal.to_feather(out_path)

    per_day = signal.groupby("date").size()
    q = signal["alpha"].quantile([0.01, 0.25, 0.5, 0.75, 0.99]).round(4).to_dict()
    fq = signal["fwd_ret"].quantile([0.01, 0.5, 0.99]).round(4).to_dict()
    log(f"信号表 {len(signal):,} 行 / {signal['id'].nunique():,} 只 / {len(per_day)} 期")
    log(f"  每期成分数 中位数={int(per_day.median())} 最小={int(per_day.min())} 最大={int(per_day.max())}")
    log(f"  alpha   分位数 {q}")
    log(f"  fwd_ret 分位数 {fq} | 覆盖率 {signal['fwd_ret'].notna().mean():.2%}")
    log(f"  dtypes {dict(signal.dtypes.astype(str))}")
    log(f"写出 -> {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
