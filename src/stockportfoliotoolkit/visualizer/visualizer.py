# ④ Visualizer：分析结果 → 图表 PNG 与数据表 CSV
from __future__ import annotations

from pathlib import Path
from typing import List

from .. import io
from ..config import VisualizerConfig
from ..contracts import WEIGHT, AnalysisResult, ContractError
from .charts import build_chart
from .tables import build_table


class Visualizer:
    def __init__(self, cfg: VisualizerConfig) -> None:
        self.cfg = cfg

    # 唯一出口：返回落盘文件清单
    def run(self, analysis: AnalysisResult) -> List[Path]:
        out_dir = io.resolve_path(self.cfg.output_dir, self.cfg.vars)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [
            *self._render_charts(analysis, out_dir),
            *self._write_tables(analysis, out_dir),
            *self._export(analysis, out_dir),
        ]

    def _render_charts(self, analysis: AnalysisResult, out_dir: Path) -> List[Path]:
        written: List[Path] = []
        for spec in self.cfg.charts:
            weights = spec.weights or sorted(analysis.curves[WEIGHT].unique())
            if not len(weights):
                raise ContractError(f"图表 '{spec.name}': 分析结果里没有任何加权方案")
            chart = build_chart(spec.type)
            for weight in weights:
                figure = chart.render(
                    analysis.curves, spec, self.cfg.style, weight, analysis.meta
                )
                path = out_dir / f"{spec.name}_{str(weight).lower()}.png"
                figure.savefig(path, dpi=self.cfg.style.dpi, bbox_inches="tight")
                written.append(path)
        return written

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
