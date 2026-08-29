# 跨截面组合回测工具包：Input → Engine → Analyzer → Visualizer 单向数据流
from .analyzer import Analyzer
from .config import AnalyzerConfig, EngineConfig, InputConfig, PipelineConfig, VisualizerConfig
from .contracts import AnalysisResult, EngineResult, InputBundle, to_legacy_wide
from .engine import PortfolioEngine
from .input import InputProcessor
from .pipeline import PipelineResult, run_pipeline
from .visualizer import Visualizer

__version__ = "0.1.0"
__all__ = [
    "InputProcessor",
    "PortfolioEngine",
    "Analyzer",
    "Visualizer",
    "run_pipeline",
    "PipelineResult",
    "InputConfig",
    "EngineConfig",
    "AnalyzerConfig",
    "VisualizerConfig",
    "PipelineConfig",
    "InputBundle",
    "EngineResult",
    "AnalysisResult",
    "to_legacy_wide",
    "__version__",
]
