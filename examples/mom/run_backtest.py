"""端到端回测：读同级 configs/ → InputProcessor → PortfolioEngine → Analyzer → Visualizer。

信号表由同级 build_signal.py 先行生成。本脚本只负责把它喂进工具包并落盘全部产物：
图 PNG、指标 CSV、IC/换手 CSV、curves.feather，外加 Engine 的逐期收益长表 returns.feather。

    python run_backtest.py                      # 用同级 configs/
    python run_backtest.py --config-dir /other/configs --no-render
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

from stockportfoliotoolkit import io
from stockportfoliotoolkit.config import VisualizerConfig
from stockportfoliotoolkit.contracts import BUCKET
from stockportfoliotoolkit.pipeline import run_pipeline

HERE = Path(__file__).resolve().parent


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="跑完整回测流水线")
    parser.add_argument("--config-dir", type=Path, default=HERE / "configs")
    parser.add_argument("--no-render", action="store_true", help="只算不出图")
    args = parser.parse_args()

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    log(f"配置目录 {args.config_dir}")
    t0 = time.time()
    result = run_pipeline(args.config_dir, render=not args.no_render)
    log(f"流水线完成，用时 {time.time() - t0:.1f}s")

    print("\n=== ① InputProcessor: bundle.meta ===", flush=True)
    print(json.dumps(result.bundle.meta, indent=2, ensure_ascii=False), flush=True)

    print("\n=== ② PortfolioEngine: engine.meta ===", flush=True)
    print(json.dumps(result.engine.meta, indent=2, ensure_ascii=False), flush=True)

    print("\n=== ③ Analyzer: 多空腿与基准 ===", flush=True)
    summary = result.analysis.summary
    headline = summary[summary[BUCKET].isin(["H-L", "REF"])]
    print(headline.round(4).to_string(index=False), flush=True)

    print("\n=== ③ Analyzer: 全部分位 ===", flush=True)
    print(summary.round(4).to_string(index=False), flush=True)

    # Engine 的逐期收益长表默认不落盘，这里补一份便于二次分析。
    # 输出目录复用 visualizer.json 的 output_dir（含 ${VAR} 展开），避免两处写死路径
    vis_cfg = VisualizerConfig.from_file(args.config_dir / "visualizer.json")
    out_dir = io.resolve_path(vis_cfg.output_dir, vis_cfg.vars)
    out_dir.mkdir(parents=True, exist_ok=True)
    returns_path = io.write_table(result.engine.returns, out_dir / "returns.feather")

    print("\n=== ④ Visualizer: 落盘文件 ===", flush=True)
    for path in [*result.outputs, returns_path]:
        print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
