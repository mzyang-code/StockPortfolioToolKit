# 面向因子研究的门面：扁平关键字参数 → 现有四个 Config → 依次驱动四个模块
#
# 本模块不含任何计算。它做三件事：把 DataFrame / 路径归一成数据源 Spec、
# 按数据推出三处默认值、把结果包成一个还能继续提问的对象。口径校验、契约校验
# 与全部数值计算仍在原模块，两条路径（本 API 与 JSON）因此不会算出不同结果。
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd
from matplotlib.figure import Figure

from . import io
from .analyzer import Analyzer
from .config_schema import (
    AnalyzerConfig,
    CalendarSpec,
    ConfigError,
    CurveSpec,
    DiagnosticsSpec,
    EngineConfig,
    ForwardReturnSpec,
    InputConfig,
    LongShortSpec,
    PipelineConfig,
    PriceSpec,
    ReferenceSpec,
    SignalSpec,
    VisualizerConfig,
)
from .contracts import (
    ALPHA,
    BUCKET,
    CAP,
    CLOSE,
    FWD_RET,
    LONG_SHORT_BUCKET,
    REFERENCE_BUCKET,
    SIGNAL,
    WEIGHT,
    AnalysisResult,
    EngineResult,
    InputBundle,
)
from .engine import PortfolioEngine
from .input import InputProcessor, provides_column
from .presets import chart_preset, table_preset
from .visualizer import Visualizer
from .visualizer.charts import build_chart

# signals / prices / references 接受的形态
TableLike = Union[pd.DataFrame, str, Path]

DEFAULT_SIGNAL_NAME = "signal"


# ============================== 输入归一 ==============================

def _as_spec(cls, value, variables: Mapping[str, str], columns=None, **extra):
    """DataFrame / 路径 / 已构造好的 Spec → Spec。其余类型在此处截断并说明可接受的形态。"""
    if isinstance(value, cls):
        return value
    if isinstance(value, pd.DataFrame):
        return cls(frame=value, column_map=dict(columns or {}), **extra)
    if isinstance(value, (str, Path)):
        return cls(path=str(value), column_map=dict(columns or {}), **extra)
    raise ConfigError(
        f"{cls.__name__} 只接受 DataFrame、文件路径或 {cls.__name__} 实例，"
        f"得到 {type(value).__name__}"
    )


def _signal_specs(signals, columns, variables) -> List[SignalSpec]:
    """单张表、{名称: 表} 或 Spec 列表 → SignalSpec 列表。"""
    if isinstance(signals, SignalSpec):
        return [signals]
    if isinstance(signals, Mapping):
        return [
            _as_spec(SignalSpec, value, variables, columns, name=str(name))
            for name, value in signals.items()
        ]
    if isinstance(signals, (list, tuple)):
        if not signals:
            raise ConfigError("signals 为空，至少需要一路 alpha 信号")
        return [
            item if isinstance(item, SignalSpec)
            else _as_spec(SignalSpec, item, variables, columns,
                          name=f"{DEFAULT_SIGNAL_NAME}{i}")
            for i, item in enumerate(signals)
        ]
    return [_as_spec(SignalSpec, signals, variables, columns, name=DEFAULT_SIGNAL_NAME)]


def _reference_specs(references, columns, frequency, variables) -> List[ReferenceSpec]:
    if references is None:
        return []
    if isinstance(references, ReferenceSpec):
        return [references]
    if isinstance(references, Mapping):
        return [
            _as_spec(ReferenceSpec, value, variables, columns,
                     name=str(name), frequency=frequency)
            for name, value in references.items()
        ]
    if isinstance(references, (list, tuple)):
        return [
            item if isinstance(item, ReferenceSpec)
            else _as_spec(ReferenceSpec, item, variables, columns,
                          name=f"benchmark{i}", frequency=frequency)
            for i, item in enumerate(references)
        ]
    return [_as_spec(ReferenceSpec, references, variables, columns,
                     name="benchmark", frequency=frequency)]


def _as_list(value, default: Sequence[str]) -> List[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [value]
    return list(value)


# ============================== 默认值推导 ==============================

# 市值加权需要 cap 列。价格面板没有市值时仍排进 weights，会产出整列 NaN 而不报错，
# 因此这里按数据决定：有 cap 才加 vw。
def _default_weights(price_spec: PriceSpec, variables: Mapping[str, str]) -> List[str]:
    return ["ew", "vw"] if provides_column(price_spec, CAP, variables) else ["ew"]


# 前视收益口径：信号自带 fwd_ret 时用自带列，否则由 close 推算。
#
# 自带列优先于 close，是因为两者的「明确程度」不对等：fwd_ret 是使用者专门算过一遍实现收益
# 的结果（常含分红与拆股调整），而 close 往往只是价格面板顺带提供的——该面板本来就要承担
# 交易日历与市值关联两项职责，有没有 close 说明不了口径意图。反过来取 close 会把那一列算好的
# 收益静默丢掉（alignment 为此专门设了 IgnoredForwardReturnWarning），两种口径在含分红的
# 数据上能差出数量级。
#
# 两者都没有时返回 prices，由 alignment._require_close 给出那条指明原因的报错。
def _default_return_source(
    price_spec: PriceSpec,
    signal_specs: Sequence[SignalSpec],
    variables: Mapping[str, str],
) -> str:
    if all(provides_column(s, FWD_RET, variables) for s in signal_specs):
        return "signals"
    return "prices"


# ============================== 门面入口 ==============================

def backtest(
    signals,
    prices,
    *,
    horizon: int,
    frequency: str = "daily",
    rebalance_freq: Optional[int] = None,
    n_buckets: int = 10,
    min_names: int = 20,
    weights=None,
    long_short: bool = True,
    long_short_reverse: bool = False,
    holding_days: Optional[int] = None,
    forward_return_source: Optional[str] = None,
    clip_lower: Optional[float] = None,
    references=None,
    reference_frequency: str = "daily",
    reference_lag: int = 1,
    first_rebalance: Optional[str] = None,
    last_rebalance: Optional[str] = None,
    calendar_source: str = "signals",
    auto_stride: bool = True,
    signal_columns: Optional[Dict[str, str]] = None,
    price_columns: Optional[Dict[str, str]] = None,
    reference_columns: Optional[Dict[str, str]] = None,
    metrics=None,
    periods_per_year: Optional[float] = None,
    trading_days_per_year: float = 252.0,
    risk_free_rate: float = 0.0,
    turnover: bool = True,
    ic: bool = True,
    ic_min_names: int = 20,
    vol_rescale_to: Optional[str] = None,
    curve_clip_lower: float = -0.99,
    shared_origin: bool = True,
    dropna: bool = True,
    restrict_to_signal_assets: bool = True,
    output_dir: Optional[str] = None,
    vars: Optional[Dict[str, str]] = None,
) -> "BacktestResult":
    """跑一次截面分位回测，返回可继续提问的结果对象。

    signals / prices 接受内存 DataFrame、文件路径，或已构造好的 Spec；多路信号用
    ``{名称: 表}`` 给出。列名与契约一致（date / id / alpha）时无需声明映射，
    不一致时用 ``signal_columns`` 等参数指明。

        bt = spt.backtest(signals=alpha_df, prices=price_df, horizon=5)
        bt.summary()
        bt.plot("long_short")

    horizon 是每期实现收益的测量期长度，必填——它定义了「一期有多长」，全包只此一处
    事实来源。rebalance_freq 留空即取同值，使相邻持有窗口首尾相接。

    frequency 声明面板的 bar 有多长，取 "daily" 或 "monthly"，horizon /
    rebalance_freq / holding_days 的单位与年化基数都随它：

        bt = spt.backtest(signals=alpha_df, prices=panel_df,
                          horizon=1, frequency="monthly")   # 月度调仓，年化按 12 期

    月度口径下前视收益与市值按自然月对齐（月末 close → h 个月后月末 close），
    因此日频价格面板配月末调仓也能直接跑。
    """
    variables = dict(vars or {})
    signal_specs = _signal_specs(signals, signal_columns, variables)
    for spec in signal_specs:
        spec.dropna = dropna
    price_spec = _as_spec(PriceSpec, prices, variables, price_columns)
    price_spec.restrict_to_signal_assets = restrict_to_signal_assets
    reference_specs = _reference_specs(
        references, reference_columns, reference_frequency, variables
    )

    # 调仓间隔与测量期不等会让相邻持有窗口重叠或留空仓缺口，净值与回撤据此失真
    # （engine._warn_on_overlap 会告警）。缺省取同值，把正确口径设成默认。
    freq = int(horizon) if rebalance_freq is None else int(rebalance_freq)

    cfg = PipelineConfig(
        input=InputConfig(
            prices=price_spec,
            signals=signal_specs,
            references=reference_specs,
            calendar=CalendarSpec(
                first_rebalance=first_rebalance,
                last_rebalance=last_rebalance,
                rebalance_freq=freq,
                source=calendar_source,
                auto_stride=auto_stride,
            ),
            frequency=frequency,
            vars=variables,
        ),
        engine=EngineConfig(
            n_buckets=n_buckets,
            min_names=min_names,
            holding_days=holding_days,
            weights=_as_list(weights, _default_weights(price_spec, variables)),
            include_references=bool(reference_specs),
            reference_lag=reference_lag,
            long_short=LongShortSpec(enabled=long_short, reverse=long_short_reverse),
            forward_return=ForwardReturnSpec(
                horizon=int(horizon),
                source=forward_return_source or _default_return_source(
                    price_spec, signal_specs, variables
                ),
                clip_lower=clip_lower,
            ),
        ),
        analyzer=AnalyzerConfig(
            **({} if metrics is None else {"metrics": _as_list(metrics, ())}),
            periods_per_year=periods_per_year,
            trading_days_per_year=trading_days_per_year,
            risk_free_rate=risk_free_rate,
            diagnostics=DiagnosticsSpec(
                turnover=turnover, ic=ic, ic_min_names=ic_min_names
            ),
            curves=CurveSpec(clip_lower=curve_clip_lower, shared_origin=shared_origin),
            **({} if vol_rescale_to is None else {
                "vol_rescale": _vol_rescale(vol_rescale_to)
            }),
        ),
        visualizer=VisualizerConfig(output_dir=output_dir, vars=variables),
    )

    bundle = InputProcessor(cfg.input).run()
    engine = PortfolioEngine(cfg.engine).run(bundle)
    analysis = Analyzer(cfg.analyzer).run(engine)
    return BacktestResult(bundle=bundle, engine=engine, analysis=analysis, config=cfg)


def _vol_rescale(reference: str):
    from .config_schema import VolRescaleSpec

    return VolRescaleSpec(enabled=True, reference=str(reference))


# ============================== 结果对象 ==============================

@dataclass(frozen=True)
class BacktestResult:
    """一次回测的全部产物。

    中间产物原样保留：returns / curves / ic / turnover 直接是 DataFrame，
    拿去做二次分析（比如把 H-L 腿接进因子回归）不需要重新跑。
    """

    bundle: InputBundle
    engine: EngineResult
    analysis: AnalysisResult
    config: PipelineConfig

    # ---------- 中间产物 ----------
    @property
    def returns(self) -> pd.DataFrame:
        """逐期组合收益长表 [date, signal_model, bucket, weight, ret, count]"""
        return self.engine.returns

    @property
    def curves(self) -> pd.DataFrame:
        """净值与累计对数收益曲线"""
        return self.analysis.curves

    @property
    def ic(self) -> pd.DataFrame:
        return self.analysis.ic

    @property
    def turnover(self) -> pd.DataFrame:
        return self.analysis.turnover

    @property
    def members(self) -> pd.DataFrame:
        """逐期分桶成分明细"""
        return self.engine.members

    @property
    def aligned(self) -> pd.DataFrame:
        """alpha × 前视收益 × 市值 的对齐面板"""
        return self.engine.aligned

    @property
    def signal_names(self) -> List[str]:
        return self.bundle.signal_names

    @property
    def weights(self) -> List[str]:
        return self.engine.weights

    @property
    def meta(self) -> Dict[str, Any]:
        return {**self.bundle.meta, **self.engine.meta, **self.analysis.meta}

    # ---------- 指标 ----------
    def summary(self, bucket=None, weight=None, signal=None) -> pd.DataFrame:
        """指标汇总表。不给参数即全部分位；bucket="H-L" 只看多空腿。"""
        frame = self.analysis.summary
        for column, wanted in ((BUCKET, bucket), (WEIGHT, weight), (SIGNAL, signal)):
            if wanted is None:
                continue
            wanted = [wanted] if isinstance(wanted, str) else list(wanted)
            frame = frame[frame[column].isin(wanted)]
        return frame.reset_index(drop=True)

    # ---------- 出图 ----------
    def plot(
        self,
        kind: str = "long_short",
        weight: Optional[str] = None,
        signal: Optional[str] = None,
        **overrides,
    ) -> Figure:
        """按预设名出一张图，返回 matplotlib Figure（可继续用原生 API 调整）。

        kind 取 "long_short"（多空腿对比）或 "deciles"（分位内部结构）。
        weight 留空取首个加权方案；多路信号画分位图时用 signal 指定看哪一路。
        样式关键字直接透传给 ChartSpec，全局样式见 spt.settings.style。
        """
        available = self.weights
        if not available:
            raise ConfigError("分析结果里没有任何加权方案")
        target = str(weight).upper() if weight is not None else available[0]
        if target not in available:
            raise ConfigError(f"未知的加权方案 {target!r}；可用项为 {available}")

        spec = chart_preset(kind, self.config.engine.n_buckets, **overrides)
        curves = self.curves
        if signal is not None:
            keep = {str(signal), *self._reference_names()}
            curves = curves[curves[SIGNAL].isin(keep)]
        elif spec.wants_split_by_signal() and len(self.signal_names) > 1:
            first = self.signal_names[0]
            curves = curves[curves[SIGNAL].isin({first, *self._reference_names()})]

        from .settings import settings

        style = self.config.visualizer.style or settings.style
        return build_chart(spec.type).render(curves, spec, style, target, self.analysis.meta)

    # REF 桶的 signal 列放的是基准名，不算一路策略，过滤信号时要跟着留下
    def _reference_names(self) -> set:
        curves = self.curves
        return set(curves[curves[BUCKET] == REFERENCE_BUCKET][SIGNAL].unique())

    # ---------- 落盘 ----------
    def save(
        self,
        output_dir=None,
        charts: Sequence[str] = ("long_short", "deciles"),
        tables: Sequence[str] = ("summary", "turnover", "ic"),
        export_returns: bool = True,
    ) -> List[Path]:
        """图 PNG 与数据表 CSV 落盘，返回文件清单。"""
        target = output_dir or self.config.visualizer.output_dir
        if target is None:
            raise ConfigError(
                "未指定落盘目录：save() 的 output_dir 或 backtest() 的 output_dir 给一个即可。"
                "内存 DataFrame 输入时没有数据文件可作落点锚，因此不猜测目录。"
            )
        n_buckets = self.config.engine.n_buckets
        cfg = VisualizerConfig(
            output_dir=str(target),
            charts=[chart_preset(k, n_buckets) for k in charts],
            tables=[table_preset(k) for k in tables],
            style=self.config.visualizer.style,
            export_returns=export_returns,
            vars=self.config.visualizer.vars,
        )
        return Visualizer(cfg).run(self.analysis)

    # ---------- 反向导出 ----------
    def to_config(self, config_dir, data_dir=None) -> List[Path]:
        """把本次实验导成四份 JSON，供 run_pipeline 复现或随论文归档。

        内存 DataFrame 无法进 JSON，因此内存输入时需给出 data_dir，表会先落盘
        再把路径写进配置——复现包本就需要数据随行。
        """
        config_dir = Path(config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        cfg = self._materialized(data_dir)

        written: List[Path] = []
        for name, section in (
            ("input", cfg.input), ("engine", cfg.engine),
            ("analyzer", cfg.analyzer), ("visualizer", cfg.visualizer),
        ):
            path = config_dir / f"{name}.json"
            path.write_text(
                json.dumps(_jsonable(section), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            written.append(path)
        return written

    # 把内存表落盘换成 path，并补上 save() 用的图表预设，使导出的配置可直接复跑
    def _materialized(self, data_dir) -> PipelineConfig:
        from copy import copy

        specs = [*self.config.input.signals, self.config.input.prices,
                 *self.config.input.references]
        in_memory = [s for s in specs if s.frame is not None]
        if in_memory and data_dir is None:
            raise ConfigError(
                "本次回测的输入是内存 DataFrame，无法写进 JSON。"
                "请给出 data_dir，表会落盘到该目录后再把路径写进配置。"
            )

        variables = dict(self.config.input.vars)
        if in_memory:
            root = Path(data_dir)
            root.mkdir(parents=True, exist_ok=True)
            for spec in in_memory:
                stem = getattr(spec, "name", None) or "prices"
                target = io.write_table(spec.frame, root / f"{_slug(stem)}.feather")
                spec.path, spec.frame = str(target), None

        n_buckets = self.config.engine.n_buckets
        visualizer = copy(self.config.visualizer)
        if not visualizer.charts:
            visualizer.charts = [chart_preset(k, n_buckets)
                                 for k in ("long_short", "deciles")]
        if not visualizer.tables:
            visualizer.tables = [table_preset(k) for k in ("summary", "turnover", "ic")]
        return PipelineConfig(
            input=self.config.input, engine=self.config.engine,
            analyzer=self.config.analyzer, visualizer=visualizer,
        )

    # ---------- notebook 里的显示 ----------
    def __repr__(self) -> str:
        engine_meta = self.engine.meta
        head = (
            f"BacktestResult(signals={self.signal_names}, "
            f"horizon={engine_meta.get('forward_horizon')}, "
            f"n_buckets={engine_meta.get('n_buckets')}, "
            f"weights={self.weights}, periods={engine_meta.get('periods')})"
        )
        headline = self.summary(bucket=[LONG_SHORT_BUCKET, REFERENCE_BUCKET])
        if headline.empty:
            return head
        return f"{head}\n{headline.round(4).to_string(index=False)}"


# 名称进文件名：非字母数字压成单个连字符，与 visualizer._slug 同规则
def _slug(name: str) -> str:
    import re

    return re.sub(r"[^0-9a-z]+", "-", str(name).lower()).strip("-") or "table"


# dataclass → 可序列化字典，跳过承载 DataFrame 的 in_memory 字段
def _jsonable(value):
    if hasattr(value, "__dataclass_fields__"):
        return {
            f.name: _jsonable(getattr(value, f.name))
            for f in fields(value)
            if not f.metadata.get("in_memory")
        }
    if isinstance(value, Mapping):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value
