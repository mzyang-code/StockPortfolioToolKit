"""把已发表的绩效表逐格对照一遍，用来分辨「实现有错」与「口径不同」。

四个预测面板 × 五个模型 × 两种加权 × 四项指标，共 40 格。对照分两步：先看
SR / Ann.Vol / MDD 能否对上——这三项一致即说明分桶、加权、前视收益对齐与多空构造
都与对方相同；在此前提下若 Ann.Ret 仍系统性对不上，差的就只剩年化口径。

    python run_repro.py                                  # 用默认数据目录
    python run_repro.py --data-dir /path/to/parquet --out /tmp/cmp.csv

面板需含 permno / eom / forward_return / MarketCap 与六个预测列，见同级 README.md。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

import alpholio as alp

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE.parent.parent / "tests" / "cache"

# 面板文件 → 对照表里的哪一列组
FILES = {
    "analyst": "merged_pred_analyst(1).parquet",
    "analyst_44": "merged_pred_analyst_44(1).parquet",
    "holding": "merged_pred_holding(1).parquet",
    "holding_44": "merged_pred_holding_44(1).parquet",
}

# 五个模型。avg_pred 是 avg_pred_low 的副本，取后者，名字与表头一致
SIGNALS = {
    "TGNN": "avg_pred_tgnn",
    "MLP": "avg_pred_mlp",
    "Low": "avg_pred_low",
    "High": "avg_pred_high",
    "ACM": "avg_pred_acm",
}

# 已发表的表格数值：{面板: {加权: {模型: (SR, Ann.Ret%, Ann.Vol%, MDD%)}}}
PAPER = {
    "analyst": {
        "VW": {"TGNN": (0.35, 5.22, 21.06, 51.51), "MLP": (0.34, 5.27, 22.03, 57.24),
               "Low": (0.30, 4.67, 27.52, 61.01), "High": (0.30, 3.56, 15.91, 48.51),
               "ACM": (0.38, 5.43, 18.13, 50.01)},
        "EW": {"TGNN": (0.95, 17.17, 18.68, 31.03), "MLP": (0.58, 8.73, 17.01, 40.27),
               "Low": (0.37, 6.37, 27.52, 55.11), "High": (1.02, 10.63, 10.43, 23.63),
               "ACM": (1.21, 14.57, 11.83, 18.21)}},
    "analyst_44": {
        "VW": {"TGNN": (1.07, 18.21, 17.03, 30.76), "MLP": (1.03, 18.63, 18.35, 46.78),
               "Low": (0.06, -1.11, 21.84, 81.79), "High": (1.19, 15.01, 12.44, 17.13),
               "ACM": (1.38, 21.02, 14.66, 21.39)},
        "EW": {"TGNN": (2.17, 41.47, 16.81, 12.37), "MLP": (1.65, 33.47, 18.73, 31.01),
               "Low": (0.21, 2.06, 22.61, 81.48), "High": (2.97, 33.13, 9.92, 6.37),
               "ACM": (3.12, 43.92, 12.08, 8.14)}},
    "holding": {
        "VW": {"TGNN": (0.36, 5.55, 21.92, 61.90), "MLP": (0.34, 5.27, 22.03, 57.24),
               "Low": (0.01, -1.10, 16.15, 63.78), "High": (0.44, 7.68, 17.97, 46.28),
               "ACM": (0.50, 7.68, 18.10, 44.72)},
        "EW": {"TGNN": (0.48, 7.69, 20.04, 65.24), "MLP": (0.58, 8.73, 17.01, 40.27),
               "Low": (0.12, 0.60, 15.23, 55.68), "High": (0.68, 8.96, 14.23, 54.19),
               "ACM": (0.76, 10.70, 15.13, 49.55)}},
    "holding_44": {
        "VW": {"TGNN": (1.08, 20.16, 18.78, 34.56), "MLP": (1.03, 18.63, 18.35, 46.78),
               "Low": (0.11, 0.51, 16.38, 60.98), "High": (1.14, 17.05, 14.85, 26.61),
               "ACM": (1.18, 20.48, 17.19, 35.59)},
        "EW": {"TGNN": (1.73, 34.77, 18.35, 22.02), "MLP": (1.65, 33.47, 18.73, 31.01),
               "Low": (0.65, 9.44, 15.71, 46.07), "High": (2.43, 34.60, 12.68, 23.98),
               "ACM": (2.55, 45.41, 15.33, 11.35)}},
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# 原始表 → 契约格式：只改列名与日期类型，不做任何数值加工。
# eom 是 '1999-06' 这样的月份串，直接 to_datetime 会落到月初，显式取月末与调仓语义一致
def to_contract(raw: pd.DataFrame) -> pd.DataFrame:
    panel = pd.DataFrame({
        "date": pd.PeriodIndex(raw["eom"], freq="M").to_timestamp(how="end").normalize(),
        "id": raw["permno"].astype("int64"),
        "cap": raw["MarketCap"],
        "fwd_ret": raw["forward_return"],
    })
    for column in SIGNALS.values():
        panel[column] = raw[column]
    return panel


# 十分位多空腿，月度调仓，实现收益取面板自带的 forward_return
def run_one(panel: pd.DataFrame) -> pd.DataFrame:
    bt = alp.backtest(
        signals={
            name: panel[["date", "id", "fwd_ret", column]].rename(columns={column: "alpha"})
            for name, column in SIGNALS.items()
        },
        prices=panel[["date", "id", "cap"]],
        horizon=1,
        frequency="monthly",
        forward_return_source="signals",
        n_buckets=10,
        min_names=20,
        turnover=False,
        ic=False,
    )
    summary = bt.summary()
    return summary[summary["bucket"] == "H-L"]


def compare(results: dict) -> pd.DataFrame:
    rows = []
    for file, by_weight in PAPER.items():
        got = results[file].set_index(["weight", "signal_model"])
        for weight, by_model in by_weight.items():
            for model, (sr, ret, vol, mdd) in by_model.items():
                row = got.loc[(weight, model)]
                rows.append({
                    "file": file, "weight": weight, "model": model,
                    "SR_paper": sr, "SR": row.sharpe, "d_SR": row.sharpe - sr,
                    "Ret_paper": ret,
                    "ann_ret": row.ann_ret * 100, "d_arith": row.ann_ret * 100 - ret,
                    "cagr": row.cagr * 100, "d_geom": row.cagr * 100 - ret,
                    "Vol_paper": vol, "ann_vol": row.ann_vol * 100,
                    "d_vol": row.ann_vol * 100 - vol,
                    "MDD_paper": mdd, "mdd": -row.max_drawdown * 100,
                    "d_mdd": -row.max_drawdown * 100 - mdd,
                })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="与已发表的绩效表逐格对照")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=None, help="对照明细落盘路径（CSV）")
    args = parser.parse_args()

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)

    missing = [name for name, f in FILES.items() if not (args.data_dir / f).exists()]
    if missing:
        print(f"数据目录 {args.data_dir} 缺少面板: {missing}", file=sys.stderr)
        print("面板不随仓库分发，路径见同级 README.md", file=sys.stderr)
        return 1

    results = {}
    for name, filename in FILES.items():
        t0 = time.time()
        raw = pd.read_parquet(args.data_dir / filename)
        results[name] = run_one(to_contract(raw))
        log(f"{name:11s} {len(raw):>8,} 行  用时 {time.time() - t0:5.1f}s")

    cmp = compare(results)
    print("\n=== 逐格对照 ===")
    print(cmp.round(2).to_string(index=False))

    print("\n=== 40 格的绝对偏差 ===")
    for column, label in [
        ("d_SR", "SR"),
        ("d_arith", "Ann.Ret（ann_ret 算术口径）"),
        ("d_geom", "Ann.Ret（cagr 复利口径）"),
        ("d_vol", "Ann.Vol"),
        ("d_mdd", "MDD"),
    ]:
        delta = cmp[column].abs()
        worst = cmp.loc[delta.idxmax(), ["file", "weight", "model"]].tolist()
        print(f"  {label:30s} 平均 {delta.mean():6.3f}  中位 {delta.median():6.3f}"
              f"  最大 {delta.max():5.2f}（{'/'.join(worst)}）")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        cmp.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
