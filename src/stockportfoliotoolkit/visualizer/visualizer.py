# ④ Visualizer：分析结果 → 图表 PNG 与数据表 CSV
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import re

from .. import io
from ..config_schema import VisualizerConfig
from ..contracts import (
    BUCKET,
    REFERENCE_BUCKET,
    SIGNAL,
    WEIGHT,
    AnalysisResult,
    ContractError,
)
from .charts import build_chart
from .tables import build_table


# output_dir 留空时，产物落到 <数据目录>/outputs
DEFAULT_OUTPUT_DIRNAME = "outputs"


# 信号名进文件名：非字母数字一律压成单个连字符
def _slug(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "-", str(name).lower()).strip("-") or "signal"


class Visualizer:
    """data_dir 是 output_dir 留空时的落点锚：产物写进 <data_dir>/outputs。

    run_pipeline 会把首路信号文件所在目录传进来，因此默认产物就落在你的数据旁边，
    而不是随进程当前工作目录漂移。
    """

    def __init__(self, cfg: VisualizerConfig, data_dir: Optional[Path] = None) -> None:
        self.cfg = cfg
        self.data_dir = Path(data_dir) if data_dir is not None else None

    # 唯一出口：返回落盘文件清单
    def run(self, analysis: AnalysisResult) -> List[Path]:
        out_dir = self._output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        return [
            *self._render_charts(analysis, out_dir),
            *self._write_tables(analysis, out_dir),
            *self._export(analysis, out_dir),
        ]

    # 显式 output_dir 优先；留空则用 <data_dir>/outputs。图和表都平铺在这一层，不再分子目录。
    def _output_dir(self) -> Path:
        if self.cfg.output_dir:
            return io.resolve_path(self.cfg.output_dir, self.cfg.vars)
        if self.data_dir is None:
            raise ContractError(
                "visualizer.output_dir 未设置，且没有可用的数据目录做落点。"
                "请在 visualizer.json 里写 output_dir，或改用 run_pipeline()"
                "（它会把产物写到首路信号文件旁边的 outputs/）。"
            )
        return self.data_dir / DEFAULT_OUTPUT_DIRNAME

    def _render_charts(self, analysis: AnalysisResult, out_dir: Path) -> List[Path]:
        written: List[Path] = []
        for spec in self.cfg.charts:
            weights = spec.weights or sorted(analysis.curves[WEIGHT].unique())
            if not len(weights):
                raise ContractError(f"图表 '{spec.name}': 分析结果里没有任何加权方案")
            chart = build_chart(spec.type)
            # 分位图逐信号出图，策略对比图把所有信号叠在一张上
            slices = self._signal_slices(analysis, spec)
            for weight in weights:
                for suffix, curves in slices:
                    figure = chart.render(curves, spec, self.cfg.style, weight, analysis.meta)
                    name = f"{spec.name}{suffix}_{str(weight).lower()}.png"
                    path = out_dir / name
                    figure.savefig(path, dpi=self.cfg.style.dpi, bbox_inches="tight")
                    written.append(path)
        return written

    # 返回 [(文件名后缀, 该图用的曲线子集)]；不拆分时就一项、后缀为空
    def _signal_slices(self, analysis: AnalysisResult, spec) -> List[tuple]:
        curves = analysis.curves
        if not spec.wants_split_by_signal():
            return [("", curves)]
        # REF 桶的 signal 是基准名，不是一路策略，不参与拆分但要跟着留在每张图里
        strategy = curves[curves[BUCKET] != REFERENCE_BUCKET]
        names = sorted(strategy[SIGNAL].unique())
        if spec.signals:
            names = [n for n in names if n in set(spec.signals)]
        if len(names) <= 1:
            return [("", curves)]
        return [
            (f"_{_slug(name)}", curves[curves[SIGNAL] == name])
            for name in names
        ]

    def _write_tables(self, analysis: AnalysisResult, out_dir: Path) -> List[Path]:
        written: List[Path] = []
        for spec in self.cfg.tables:
            frame = build_table(spec.type).build(analysis, spec)
            written.append(io.write_table(frame, out_dir / f"{spec.name}.csv"))
        return written

    # 完整长表另存一份，便于二次分析
    def _export(self, analysis: AnalysisResult, out_dir: Path) -> List[Path]:
        if not self.cfg.export_returns:
            return []
        return [
            io.write_table(analysis.summary, out_dir / "summary_metrics.csv"),
            io.write_table(analysis.curves, out_dir / "curves.feather"),
        ]
