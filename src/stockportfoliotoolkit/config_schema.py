# 四个模块各自的 JSON 配置：加载、严格校验、缺省合并
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Type, TypeVar

import pandas as pd

from .frequency import FREQUENCIES

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
    # in_memory 字段承载 DataFrame，无法序列化，不属于 JSON 可写项
    names = {f.name for f in fields(cls) if not f.metadata.get("in_memory")}
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


# 内存数据源字段。compare=False 是必需的：dataclass 自动生成的 __eq__ 拿两个内容相同
# 但非同一对象的 DataFrame 相比会抛「truth value is ambiguous」。repr=False 则避免
# 整张表被打进错误信息。
def _frame() -> Any:
    return field(default=None, compare=False, repr=False, metadata={"in_memory": True})


# path 与 frame 恰好给出一个：两个都给无从判断以哪个为准，都不给则没有数据来源
def _check_source(spec, ctx: str) -> None:
    has_path, has_frame = bool(spec.path), spec.frame is not None
    if has_path and has_frame:
        raise ConfigError(f"{ctx}: path 与 frame 只能给一个，不能同时指定")
    if not has_path and not has_frame:
        raise ConfigError(f"{ctx}: 必须给出 path（文件路径）或 frame（内存 DataFrame）")


# ============================== ① Input ==============================
# 三个数据源 Spec 同构：数据来自 path 指向的文件，或 frame 持有的内存 DataFrame。
# column_map 留空时按契约列名（date / id / alpha 等）在源表中同名匹配，
# 源列名与契约一致的表因此无需声明映射。
@dataclass
class SignalSpec:
    name: str
    path: Optional[str] = None
    column_map: Dict[str, str] = field(default_factory=dict)
    format: Optional[str] = None
    dropna: bool = True
    read_kwargs: Dict[str, Any] = field(default_factory=dict)
    frame: Optional[pd.DataFrame] = _frame()

    def __post_init__(self) -> None:
        _check_source(self, f"input.signals[{self.name}]")


@dataclass
class PriceSpec:
    path: Optional[str] = None
    column_map: Dict[str, str] = field(default_factory=dict)
    format: Optional[str] = None
    restrict_to_signal_assets: bool = True
    read_kwargs: Dict[str, Any] = field(default_factory=dict)
    frame: Optional[pd.DataFrame] = _frame()

    def __post_init__(self) -> None:
        _check_source(self, "input.prices")


@dataclass
class ReferenceSpec:
    name: str
    path: Optional[str] = None
    column_map: Dict[str, str] = field(default_factory=dict)
    format: Optional[str] = None
    frequency: str = "daily"  # daily=按持有期复利, period=已是周期收益直接对齐
    read_kwargs: Dict[str, Any] = field(default_factory=dict)
    frame: Optional[pd.DataFrame] = _frame()

    def __post_init__(self) -> None:
        _check_source(self, f"input.references[{self.name}]")


@dataclass
class CalendarSpec:
    first_rebalance: Optional[str] = None
    last_rebalance: Optional[str] = None
    # 调仓间隔，单位随 input.frequency：日度为交易日，月度为自然月
    rebalance_freq: int = 5
    source: str = "signals"  # signals | prices
    auto_stride: bool = True  # 信号日历原生已够稀疏时不再二次抽稀


@dataclass
class InputConfig:
    prices: PriceSpec = _nested(PriceSpec)
    signals: List[SignalSpec] = _nested(SignalSpec, many=True, default_factory=list)
    references: List[ReferenceSpec] = _nested(ReferenceSpec, many=True, default_factory=list)
    calendar: CalendarSpec = _nested(CalendarSpec, default_factory=CalendarSpec)
    # 面板的 bar 有多长：daily=一行一个交易日, monthly=一行一个自然月。
    # 全包只此一处声明，下游四件事都以它为准——日历抽稀单位、前视收益测量方式、
    # 日频基准的复利窗口、年化基数。
    frequency: str = "daily"
    vars: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        key = str(self.frequency).lower()
        if key not in FREQUENCIES:
            raise ConfigError(
                f"input.frequency 只能取 {sorted(FREQUENCIES)}，得到 {self.frequency!r}"
            )
        self.frequency = key

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


class HoldingPeriodWarning(UserWarning):
    """holding_days 与 forward_return.horizon 不一致：可算，但口径需自证"""


@dataclass
class ForwardReturnSpec:
    # 前视收益的测量期长度，单位随 input.frequency（日度=交易日，月度=自然月）。必填：
    # 它定义了每期实现收益跨越多长的窗口，也是全包唯一一处「一期有多长」的事实来源。
    horizon: Optional[int] = None
    source: str = "prices"  # prices=close 前视收益, signals=信号文件自带列
    clip_lower: Optional[float] = None


@dataclass
class EngineConfig:
    n_buckets: int = 10
    min_names: int = 20
    # 年化折算所用的持有期数，单位随 input.frequency（日度=交易日，月度=自然月）。
    # 留空即继承 forward_return.horizon；显式给出且不等时告警但不中断
    holding_days: Optional[int] = None
    weights: List[str] = field(default_factory=lambda: ["ew", "vw"])
    weight_options: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    include_references: bool = True
    reference_lag: int = 1  # 日频基准复利起点相对锚点的偏移：1=次日(与持仓对齐), 0=当日
    long_short: LongShortSpec = _nested(LongShortSpec, default_factory=LongShortSpec)
    forward_return: ForwardReturnSpec = _nested(
        ForwardReturnSpec, default_factory=ForwardReturnSpec
    )

    # 在 __post_init__ 里做，JSON 路径与 EngineConfig(...) 直接构造都会走到
    def __post_init__(self) -> None:
        spec = self.forward_return
        if spec is None or spec.horizon is None:
            raise ConfigError(
                "engine.forward_return.horizon 为必填项：请写明前视收益的测量期长度，"
                "单位随 input.frequency（日度=交易日，月度=自然月）。"
                "holding_days 未单独指定时即继承该值。"
            )
        horizon = int(spec.horizon)
        if horizon < 1:
            raise ConfigError(f"engine.forward_return.horizon 必须 >= 1，得到 {spec.horizon}")
        spec.horizon = horizon

        if self.holding_days is None:
            self.holding_days = horizon
            return
        self.holding_days = int(self.holding_days)
        if self.holding_days < 1:
            raise ConfigError(f"engine.holding_days 必须 >= 1，得到 {self.holding_days}")
        if self.holding_days != horizon:
            warnings.warn(
                f"engine.holding_days={self.holding_days} 与 "
                f"engine.forward_return.horizon={horizon} 不一致："
                f"每期实现收益按 {horizon} 期测量（基准同窗口口径），"
                f"而年化因子按每年「年化基数/{self.holding_days}」期折算"
                f"（基数随 input.frequency：日度取 analyzer.trading_days_per_year，"
                f"默认 252；月度取 12）。"
                f"两者不等意味着组合收益的测量期与声称的持有期不是同一件事，"
                f"年化收益/波动/夏普会相应偏移；确属有意为之可忽略本条。",
                HoldingPeriodWarning,
                stacklevel=3,
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

# 分位色阶模式的名字，与 visualizer.style.GRADIENT_MODE 同值（此处不 import 以免循环）
GRADIENT_MODE = "gradient"


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
    # 多信号时是否每路信号单独出一张图。留空=自动（见 wants_split_by_signal）
    split_by_signal: Optional[bool] = None
    # 图例：留空则跟随 style，同样限四个角
    legend_loc: Optional[str] = None
    legend_ncol: Optional[int] = None
    # 图例文案，支持 {signal} / {bucket}；留空则 gradient 用 "Decile n"、其余用 "信号 桶"
    legend_label: Optional[str] = None

    def __post_init__(self) -> None:
        if self.legend_loc is not None:
            _check_legend_loc(self.legend_loc, f"visualizer.charts[{self.name}].legend_loc")

    # 分位图：把一路信号拆成各分位看内部结构。本包里它等价于 color_mode="gradient"
    # ——色阶正是按分位铺开的。策略对比图（H-L 腿）则用 palette 模式。
    @property
    def is_decile_view(self) -> bool:
        return str(self.color_mode).lower() == GRADIENT_MODE

    # 分位图每路信号单独成图：两路信号 × 10 个分位叠在一起没法读。
    # 策略对比图恰恰相反——多路信号必须同图才谈得上比较。
    def wants_split_by_signal(self) -> bool:
        if self.split_by_signal is not None:
            return bool(self.split_by_signal)
        return self.is_decile_view


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
    # 留空 = 落到数据文件同级的 outputs/（由 run_pipeline 定位）。
    # 写相对路径的话按进程当前工作目录解析，跨目录启动会漂移，建议要么留空要么写绝对路径。
    output_dir: Optional[str] = None
    charts: List[ChartSpec] = _nested(ChartSpec, many=True, default_factory=list)
    tables: List[TableSpec] = _nested(TableSpec, many=True, default_factory=list)
    # 留空 = 渲染时取 settings.style（见 Visualizer.__init__），使全局样式改动对
    # 未显式声明样式的配置生效。JSON 里写了 style 则以 JSON 为准，不受全局影响。
    style: Optional[StyleSpec] = _nested(StyleSpec, default=None)
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
