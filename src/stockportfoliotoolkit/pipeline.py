# 端到端编排：四个模块依次串联，中间产物全部保留
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import io
from .analyzer import Analyzer
from .config_schema import PipelineConfig
from .contracts import AnalysisResult, EngineResult, InputBundle
from .engine import PortfolioEngine
from .input import InputProcessor
from .visualizer import Visualizer


@dataclass(frozen=True)
class PipelineResult:
    bundle: InputBundle
    engine: EngineResult
    analysis: AnalysisResult
    outputs: List[Path]


def run_pipeline(config_dir: Path, render: bool = True) -> PipelineResult:
    cfg = PipelineConfig.from_dir(config_dir)
    bundle = InputProcessor(cfg.input).run()
    engine = PortfolioEngine(cfg.engine).run(bundle)
    analysis = Analyzer(cfg.analyzer).run(engine)
    visualizer = Visualizer(cfg.visualizer, data_dir=_data_dir(cfg))
    outputs = visualizer.run(analysis) if render else []
    return PipelineResult(bundle=bundle, engine=engine, analysis=analysis, outputs=outputs)


# visualizer.output_dir 留空时的落点锚：首路信号文件所在目录。
# 选信号而非价格，是因为价格面板通常是多个项目共用的只读数据，不该往里写产物。
# 内存 DataFrame 输入时没有路径可作锚，返回 None 交由 Visualizer._output_dir 报错，
# 不猜测落点、也不悄悄写进当前工作目录。
def _data_dir(cfg: PipelineConfig) -> Optional[Path]:
    specs = cfg.input.signals
    if not specs or not specs[0].path:
        return None
    return io.resolve_path(specs[0].path, cfg.input.vars).parent
