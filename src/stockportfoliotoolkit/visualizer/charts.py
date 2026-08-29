# 图表：脱离 pyplot 全局状态，直接构造 Figure
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

import matplotlib as mpl
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import ScalarFormatter

from ..config import ChartSpec, StyleSpec
from ..contracts import (
    BUCKET,
    CUM_LOG_RET,
    DATE,
    EQUITY,
    REFERENCE_BUCKET,
    SIGNAL,
    WEIGHT,
    bucket_rank,
)
from ..registry import Registry
from .style import BUCKET_LABEL, GRADIENT_MODE, SOLE_SIGNAL_LABEL, Palette

CHARTS: Registry = Registry("chart")

TICK_FONTSIZE = 13.0  # 刻度字号固定，不开放配置


class Chart(ABC):
    name: str = ""
    value_column: str = ""
    default_title: str = ""
    default_xlabel: str = "Date"
    default_ylabel: str = ""
    baseline: Optional[float] = None

    @abstractmethod
    def render(
        self,
        curves: pd.DataFrame,
        spec: ChartSpec,
        style: StyleSpec,
        weight: str,
        meta: Optional[Dict] = None,
    ) -> Figure:
        ...


class _LineChart(Chart):
    def render(
        self,
        curves: pd.DataFrame,
        spec: ChartSpec,
        style: StyleSpec,
        weight: str,
        meta: Optional[Dict] = None,
    ) -> Figure:
        data = _select(curves, spec, weight)
        groups = sorted(
            data.groupby([SIGNAL, BUCKET], sort=False),
            key=lambda item: (item[0][0], bucket_rank(item[0][1]), item[0][1]),
        )
        styles = Palette(style).assign([key for key, _ in groups], spec.color_mode)
        # REF 桶的 "signal" 是基准名，不算一路信号
        label_template = _label_template(
            spec, {s for (s, bucket), _ in groups if bucket != REFERENCE_BUCKET}
        )
        fig = Figure(figsize=tuple(style.figsize))
        ax = fig.subplots()

        for (signal, bucket), line in groups:
            line = line.sort_values(DATE)
            ax.plot(
                line[DATE], line[self.value_column],
                label=Palette.label(signal, bucket, label_template),
                **styles[(signal, bucket)],
            )
        if not len(data):
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        if spec.show_baseline and self.baseline is not None:
            ax.axhline(
                self.baseline, color=style.baseline_color,
                linewidth=style.baseline_linewidth, zorder=1,
            )

        suffix = " — vol-rescaled" if (meta or {}).get("vol_rescaled") else ""
        context = {
            "weight": str(weight),
            "weight_label": _weight_label(weight, style),
            "chart": spec.name,
        }
        if spec.show_title:
            ax.set_title(
                _text(spec.title, self.default_title, context) + suffix,
                fontsize=style.title_fontsize,
            )
        if _enabled(spec.show_xlabel, spec.xlabel):
            ax.set_xlabel(
                _text(spec.xlabel, self.default_xlabel, context), fontsize=style.label_fontsize
            )
        if _enabled(spec.show_ylabel, spec.ylabel):
            ax.set_ylabel(
                _text(spec.ylabel, self.default_ylabel, context) + suffix,
                fontsize=style.label_fontsize,
            )
        ax.yaxis.set_major_formatter(TrimmedTickFormatter())
        ax.tick_params(axis="both", labelsize=TICK_FONTSIZE)
        ax.grid(True, alpha=style.grid_alpha)
        _place_legend(ax, len(groups), style, spec.legend_loc, spec.legend_ncol)
        fig.autofmt_xdate()
        fig.tight_layout()
        return fig


@CHARTS.register()
class CumulativeLogReturnChart(_LineChart):
    name = "cumulative_log_return"
    value_column = CUM_LOG_RET
    default_title = "Cumulative Returns of {weight_label} Portfolios"
    default_ylabel = "Cumulative Log Return"
    baseline = 0.0


@CHARTS.register()
class EquityCurveChart(_LineChart):
    name = "equity"
    value_column = EQUITY
    default_title = "Cumulative Returns of {weight_label} Portfolios"
    default_ylabel = "Equity"
    baseline = 1.0


# 刻度去尾零：0.00→0, 0.50→0.5, 1.00→1；科学计数等非小数格式原样放行
class TrimmedTickFormatter(ScalarFormatter):
    def __call__(self, x, pos=None) -> str:
        if x == 0:
            return "0"
        text = super().__call__(x, pos)
        if "." not in text or "e" in text.lower():
            return text
        return text.rstrip("0").rstrip(".")


# 灰边白底的半透明浮框；位置限四个角，per-chart 可覆盖全局设置
def _place_legend(
    ax,
    n_lines: int,
    style: StyleSpec,
    loc: Optional[str] = None,
    ncol: Optional[int] = None,
) -> None:
    if not n_lines:
        return
    legend = ax.legend(
        loc=(loc or style.legend_loc).lower(),
        ncol=max(1, int(style.legend_ncol if ncol is None else ncol)),
        fontsize=style.legend_fontsize,
        frameon=True,
    )
    frame = legend.get_frame()
    frame.set_facecolor(mpl.colors.to_rgba(style.legend_facecolor, style.legend_alpha))
    frame.set_edgecolor(style.legend_edgecolor)
    frame.set_linewidth(style.legend_linewidth)
    frame.set_alpha(None)  # 透明度只由 facecolor 的 alpha 决定，边线保持实色


# 信号名只在同图多信号时才有信息量，其余情况从图例里省掉
def _label_template(spec: ChartSpec, signals: set) -> Optional[str]:
    if spec.legend_label is not None:
        return spec.legend_label
    if str(spec.color_mode).lower() == GRADIENT_MODE:
        return BUCKET_LABEL
    return SOLE_SIGNAL_LABEL if len(signals) <= 1 else None


# 显式写了文案就视同打开该标签
def _enabled(flag: bool, custom: Optional[str]) -> bool:
    return bool(flag) or custom is not None


# 占位符缺失时原样返回，避免自定义文案里的花括号把出图打断
def _text(custom: Optional[str], default: str, context: Dict[str, str]) -> str:
    template = default if custom is None else custom
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        return template


def _weight_label(weight: str, style: StyleSpec) -> str:
    key = str(weight).upper()
    return style.weight_labels.get(key, key)


# 按 weight / bucket / signal 依次过滤
def _select(curves: pd.DataFrame, spec: ChartSpec, weight: str) -> pd.DataFrame:
    data = curves[curves[WEIGHT] == weight]
    if spec.buckets:
        data = data[data[BUCKET].isin(spec.buckets)]
    if spec.signals:
        data = data[data[SIGNAL].isin(spec.signals)]
    return data


def build_chart(kind: str) -> Chart:
    return CHARTS.get(kind)()
