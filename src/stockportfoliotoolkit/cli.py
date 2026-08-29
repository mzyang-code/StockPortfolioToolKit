# 命令行入口：spt run --config-dir <目录>
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import BUCKET
from .pipeline import run_pipeline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="spt", description="截面组合回测工具包")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="按配置目录跑完整流水线")
    run.add_argument("--config-dir", "-c", type=Path, required=True)
    run.add_argument("--no-render", action="store_true", help="只算不出图")
    run.add_argument("--quiet", "-q", action="store_true")

    args = parser.parse_args(argv)
    result = run_pipeline(args.config_dir, render=not args.no_render)

    if not args.quiet:
        print(json.dumps(result.bundle.meta, indent=2, ensure_ascii=False))
        headline = result.analysis.summary
        headline = headline[headline[BUCKET].isin(["H-L", "REF"])]
        if not headline.empty:
            print("\n=== headline metrics ===")
            print(headline.round(4).to_string(index=False))
    for path in result.outputs:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
