# 端到端编排：四个模块依次串联，中间产物全部保留
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from .analyzer import Analyzer
from .config import PipelineConfig
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
    outputs = Visualizer(cfg.visualizer).run(analysis) if render else []
    return PipelineResult(bundle=bundle, engine=engine, analysis=analysis, outputs=outputs)
