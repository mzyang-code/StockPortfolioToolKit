# 四个模块各自的 JSON 配置：加载、严格校验、缺省合并
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Type, TypeVar

T = TypeVar("T")


class ConfigError(ValueError):
    """配置文件结构错误"""


def load_json(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"配置根节点必须是对象: {path}")
    return data


# 按 dataclass 字段严格构造：未知键报错，避免拼写错误被静默吞掉
def _strict(cls: Type[T], data: Mapping[str, Any], ctx: str) -> T:
    if not isinstance(data, Mapping):
        raise ConfigError(f"{ctx}: 期望对象，得到 {type(data).__name__}")
    names = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ConfigError(f"{ctx}: 未知配置项 {unknown}；可用项为 {sorted(names)}")
    kwargs: Dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        sub = f.metadata.get("dataclass")
        if sub is not None and value is not None:
            if f.metadata.get("many"):
                value = [_strict(sub, v, f"{ctx}.{f.name}[{i}]") for i, v in enumerate(value)]
            else:
                value = _strict(sub, value, f"{ctx}.{f.name}")
        kwargs[f.name] = value
    return cls(**kwargs)


def _nested(sub: type, many: bool = False, **kw) -> Any:
    return field(metadata={"dataclass": sub, "many": many}, **kw)


# ============================== ① Input ==============================
@dataclass
class SignalSpec:
    name: str
    path: str
    column_map: Dict[str, str]
    format: Optional[str] = None
    dropna: bool = True
    read_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceSpec:
    path: str
    column_map: Dict[str, str]
    format: Optional[str] = None
    restrict_to_signal_assets: bool = True
    read_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReferenceSpec:
    name: str
    path: str
    column_map: Dict[str, str]
    format: Optional[str] = None
    frequency: str = "daily"  # daily=按持有期复利, period=已是周期收益直接对齐
    read_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CalendarSpec:
    first_rebalance: Optional[str] = None
    last_rebalance: Optional[str] = None
    rebalance_freq: int = 5
    source: str = "signals"  # signals | prices
    auto_stride: bool = True  # 信号日历原生已够稀疏时不再二次抽稀


@dataclass
class InputConfig:
    prices: PriceSpec = _nested(PriceSpec)
    signals: List[SignalSpec] = _nested(SignalSpec, many=True, default_factory=list)
    references: List[ReferenceSpec] = _nested(ReferenceSpec, many=True, default_factory=list)
    calendar: CalendarSpec = _nested(CalendarSpec, default_factory=CalendarSpec)
    vars: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InputConfig":
        return _strict(cls, data, "input")

    @classmethod
    def from_file(cls, path: Path) -> "InputConfig":
        return cls.from_dict(load_json(path))


# ============================== ② Engine ==============================
@dataclass
class LongShortSpec:
    enabled: bool = True
    label: str = "H-L"
    reverse: bool = False  # 默认高分位减低分位，打开则反向


@dataclass
class ForwardReturnSpec:
    source: str = "prices"  # prices=close 前视收益, signals=信号文件自带列
    clip_lower: Optional[float] = None


@dataclass
class EngineConfig:
    n_buckets: int = 10
    min_names: int = 20
    holding_days: int = 5
    weights: List[str] = field(default_factory=lambda: ["ew", "vw"])
    weight_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    include_references: bool = True
    reference_lag: int = 1  # 日频基准复利起点相对锚点的偏移：1=次日(与持仓对齐), 0=当日
    long_short: LongShortSpec = _nested(LongShortSpec, default_factory=LongShortSpec)
    forward_return: ForwardReturnSpec = _nested(
        ForwardReturnSpec, default_factory=ForwardReturnSpec
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EngineConfig":
        return _strict(cls, data, "engine")

    @classmethod
    def from_file(cls, path: Path) -> "EngineConfig":
        return cls.from_dict(load_json(path))


# ============================== ③ Analyzer ==============================
@dataclass
class DiagnosticsSpec:
    turnover: bool = True
    ic: bool = True
    ic_min_names: int = 20


@dataclass
class CurveSpec:
    clip_lower: float = -0.99
    shared_origin: bool = True


@dataclass
class VolRescaleSpec:
    enabled: bool = False  # 打开后所有收益整体缩放，需同时给出 reference
    reference: Optional[str] = None  # 缩放目标，取某个信号/基准名
    min_periods: int = 20


@dataclass
class AnalyzerConfig:
    metrics: List[str] = field(
        default_factory=lambda: [
            "ann_ret", "ann_vol", "sharpe", "max_drawdown", "total_equity",
        ]
    )
    periods_per_year: Optional[float] = None
    trading_days_per_year: float = 252.0
    risk_free_rate: float = 0.0
    diagnostics: DiagnosticsSpec = _nested(DiagnosticsSpec, default_factory=DiagnosticsSpec)
    curves: CurveSpec = _nested(CurveSpec, default_factory=CurveSpec)
    vol_rescale: VolRescaleSpec = _nested(VolRescaleSpec, default_factory=VolRescaleSpec)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalyzerConfig":
        return _strict(cls, data, "analyzer")

    @classmethod
    def from_file(cls, path: Path) -> "AnalyzerConfig":
        return cls.from_dict(load_json(path))


# ============================== ④ Visualizer ==============================
# 图例只允许落在四个角，别处会挡住曲线
LEGEND_CORNERS = ("upper left", "upper right", "lower left", "lower right")


def _check_legend_loc(value: str, ctx: str) -> None:
    if str(value).lower() not in LEGEND_CORNERS:
        raise ConfigError(f"{ctx}: 图例位置只能取 {list(LEGEND_CORNERS)}，得到 {value!r}")


@dataclass
class ChartSpec:
    name: str
    type: str = "cumulative_log_return"
    buckets: List[str] = field(default_factory=lambda: ["H-L"])
    weights: Optional[List[str]] = None
    signals: Optional[List[str]] = None
    color_mode: str = "palette"  # palette=按信号配色, gradient=分位走色阶
    # 文案支持 {weight} / {weight_label} 占位符；留空即用图表类型自带的默认标题
    title: Optional[str] = None
    show_title: bool = True
    xlabel: Optional[str] = None
    ylabel: Optional[str] = None
    # 轴标签默认不画；显式写了 xlabel/ylabel 视同打开
    show_xlabel: bool = False
    show_ylabel: bool = False
    show_baseline: bool = False  # 基准横线（累计对数收益 0 / 净值 1）默认不画
    # 图例：留空则跟随 style，同样限四个角
    legend_loc: Optional[str] = None
    legend_ncol: Optional[int] = None
    # 图例文案，支持 {signal} / {bucket}；留空则 gradient 用 "Decile n"、其余用 "信号 桶"
    legend_label: Optional[str] = None

    def __post_init__(self) -> None:
        if self.legend_loc is not None:
            _check_legend_loc(self.legend_loc, f"visualizer.charts[{self.name}].legend_loc")


@dataclass
class TableSpec:
    name: str
    type: str = "summary"
    buckets: Optional[List[str]] = None
    weights: Optional[List[str]] = None
    signals: Optional[List[str]] = None
    percent_columns: List[str] = field(
        default_factory=lambda: ["ann_ret", "ann_vol", "max_drawdown", "turnover"]
    )
    decimals: int = 3


@dataclass
class StyleSpec:
    figsize: List[float] = field(default_factory=lambda: [12.0, 6.5])
    dpi: int = 160
    linewidth: float = 1.7
    grid_alpha: float = 0.25
    title_fontsize: float = 13.0
    label_fontsize: float = 11.0
    # 图例：灰边白底的浮框，压在曲线上方
    legend_loc: str = "upper left"
    legend_fontsize: float = 10.0
    legend_ncol: int = 1
    legend_facecolor: str = "#ffffff"
    legend_edgecolor: str = "#808080"
    legend_alpha: float = 0.5  # 只作用于底色，边线保持实色
    legend_linewidth: float = 0.8
    # 基准横线样式，仅在 charts[].show_baseline 打开时生效
    baseline_color: str = "#444444"
    baseline_linewidth: float = 0.7
    # 加权方案 → 标题里的人话，未登记的方案直接用大写代号
    weight_labels: Dict[str, str] = field(
        default_factory=lambda: {
            "EW": "Equal-Weighted",
            "VW": "Value-Weighted",
            "LOGVW": "Log-Cap-Weighted",
        }
    )
    palette: Dict[str, str] = field(default_factory=dict)
    fallback_colors: List[str] = field(
        default_factory=lambda: [
            "#1f77b4", "#1a7f37", "#cf222e", "#bf8700",
            "#8250df", "#0969da", "#953800", "#57606a",
        ]
    )
    reference_color: str = "#7f7f7f"
    reference_linestyle: str = "--"
    # gradient 模式：分位桶取色阶，多空腿单独强调
    gradient_colormap: str = "viridis"
    gradient_range: List[float] = field(default_factory=lambda: [0.08, 0.92])
    highlight_color: str = "#d62728"
    highlight_linewidth: float = 2.6

    def __post_init__(self) -> None:
        _check_legend_loc(self.legend_loc, "visualizer.style.legend_loc")


@dataclass
class VisualizerConfig:
    output_dir: str = "./outputs"
    charts: List[ChartSpec] = _nested(ChartSpec, many=True, default_factory=list)
    tables: List[TableSpec] = _nested(TableSpec, many=True, default_factory=list)
    style: StyleSpec = _nested(StyleSpec, default_factory=StyleSpec)
    export_returns: bool = True
    vars: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisualizerConfig":
        return _strict(cls, data, "visualizer")

    @classmethod
    def from_file(cls, path: Path) -> "VisualizerConfig":
        return cls.from_dict(load_json(path))


@dataclass
class PipelineConfig:
    input: InputConfig
    engine: EngineConfig
    analyzer: AnalyzerConfig
    visualizer: VisualizerConfig

    # 目录内固定四个文件名，缺任一即报错
    @classmethod
    def from_dir(cls, config_dir: Path) -> "PipelineConfig":
        config_dir = Path(config_dir)
        return cls(
            input=InputConfig.from_file(config_dir / "input.json"),
            engine=EngineConfig.from_file(config_dir / "engine.json"),
            analyzer=AnalyzerConfig.from_file(config_dir / "analyzer.json"),
            visualizer=VisualizerConfig.from_file(config_dir / "visualizer.json"),
        )


assert all(is_dataclass(c) for c in (InputConfig, EngineConfig, AnalyzerConfig, VisualizerConfig))
