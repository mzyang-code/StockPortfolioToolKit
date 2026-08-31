# 跨截面组合回测工具包：Input → Engine → Analyzer → Visualizer 单向数据流
from .analyzer import Analyzer
from .config_schema import AnalyzerConfig, EngineConfig, InputConfig, PipelineConfig, VisualizerConfig
from .contracts import AnalysisResult, EngineResult, InputBundle, to_legacy_wide
from .engine import PortfolioEngine
from .input import InputProcessor
from .pipeline import PipelineResult, run_pipeline
from .visualizer import Visualizer

__version__ = "0.2.0"
__all__ = [
    # 核心类
    "InputProcessor",
    "PortfolioEngine",
    "Analyzer",
    "Visualizer",

    # 辅助函数和数据类
    "run_pipeline",
    "PipelineResult",
    "InputConfig",
    "EngineConfig",
    "AnalyzerConfig",
    "VisualizerConfig",
    "PipelineConfig",

    # 用于流转的中间产物
    "InputBundle",
    "EngineResult",
    "AnalysisResult",

    # 格式转换函数
    "to_legacy_wide",

    # 版本号
    "__version__",
]
