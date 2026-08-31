# Visualizer：配色分配、图面元素与落盘
from __future__ import annotations

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from matplotlib.legend import Legend

from stockportfoliotoolkit.benchmark import (
    BENCHMARK_STYLE,
    benchmark_curve,
    benchmark_label,
    load_sp500_daily,
)
from stockportfoliotoolkit.config_schema import ChartSpec, ConfigError, StyleSpec
from stockportfoliotoolkit.contracts import bucket_rank, sort_by_bucket
from stockportfoliotoolkit.visualizer import Palette, build_chart
from stockportfoliotoolkit.visualizer.charts import TICK_FONTSIZE

BLUE, GREEN = "#1f77b4", "#1a7f37"
DECILES = [("S", str(i)) for i in range(10)] + [("S", "H-L")]


def _curves(buckets=("H-L",), signals=("S",)) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=6)
    return pd.concat(
        [
            pd.DataFrame({
                "date": dates,
                "signal_model": signal,
                "bucket": bucket,
                "weight": weight,
                "cum_log_ret": np.linspace(-0.05, 0.05, len(dates)),
                "equity": np.exp(np.linspace(-0.05, 0.05, len(dates))),
            })
            for weight in ("EW", "VW")
            for signal in signals
            for bucket in buckets
        ],
        ignore_index=True,
    )


# 默认关掉内置基准，让这些用例只盯自己要断言的那几条线；
# 基准本身另有 test_benchmark 一组用例覆盖
def _render(weight: str = "EW", **overrides):
    overrides.setdefault("show_benchmark", False)
    spec = ChartSpec(name="curve", **overrides)
    buckets = tuple(spec.buckets) if spec.buckets else ("H-L",)
    signals = tuple(spec.signals) if spec.signals else ("S",)
    figure = build_chart(spec.type).render(
        _curves(buckets, signals), spec, StyleSpec(), weight
    )
    return figure.axes[0]


# 同一信号的多个桶必须拿到不同颜色，否则图上两条线重叠难辨
def test_same_signal_different_buckets_get_distinct_colors():
    styles = Palette(StyleSpec(palette={"S": BLUE})).assign([("S", "0"), ("S", "9")])
    assert styles[("S", "0")]["color"] != styles[("S", "9")]["color"]


# 信号级配色只在该信号只有一条线时生效
def test_signal_palette_applies_to_single_line():
    styles = Palette(StyleSpec(palette={"S": BLUE})).assign([("S", "H-L"), ("T", "H-L")])
    assert styles[("S", "H-L")]["color"] == BLUE
    assert styles[("T", "H-L")]["color"] != BLUE


def test_precise_key_wins_over_signal_key():
    spec = StyleSpec(palette={"S": BLUE, "S 9": GREEN})
    styles = Palette(spec).assign([("S", "0"), ("S", "9")])
    assert styles[("S", "9")]["color"] == GREEN


def test_reference_bucket_uses_dashed_style():
    styles = Palette(StyleSpec()).assign([("S", "H-L"), ("B", "REF")])
    assert styles[("B", "REF")]["linestyle"] == "--"
    assert styles[("S", "H-L")]["linestyle"] == "-"


def test_fallback_colors_do_not_collide_with_explicit():
    spec = StyleSpec(palette={"A": BLUE}, fallback_colors=[BLUE, GREEN])
    styles = Palette(spec).assign([("A", "H-L"), ("B", "H-L")])
    assert styles[("B", "H-L")]["color"] == GREEN


# gradient 模式：10 个分位取到 10 个互不相同的色阶
def test_gradient_gives_every_decile_its_own_shade():
    styles = Palette(StyleSpec()).assign(DECILES, mode="gradient")
    shades = [styles[("S", str(i))]["color"] for i in range(10)]
    assert len(set(shades)) == 10


# 多空腿用强调色加粗，并压在分位线之上
def test_gradient_highlights_long_short():
    spec = StyleSpec()
    styles = Palette(spec).assign(DECILES, mode="gradient")
    hl, decile = styles[("S", "H-L")], styles[("S", "0")]
    assert hl["color"] == spec.highlight_color
    assert hl["linewidth"] == spec.highlight_linewidth > decile["linewidth"]
    assert hl["zorder"] > decile["zorder"]


def test_gradient_reference_stays_dashed():
    styles = Palette(StyleSpec()).assign([("S", "0"), ("B", "REF")], mode="gradient")
    assert styles[("B", "REF")]["linestyle"] == "--"


# ---------------------------------------------------------------- 图面元素

# 标题默认由加权方案决定，EW / VW 各自说人话
def test_default_title_follows_weight():
    assert _render("EW").get_title() == "Cumulative Returns of Equal-Weighted Portfolios"
    assert _render("VW").get_title() == "Cumulative Returns of Value-Weighted Portfolios"


def test_custom_title_may_template_the_weight():
    assert _render("VW", title="H-L ({weight_label})").get_title() == "H-L (Value-Weighted)"


# 未登记的加权方案退回大写代号，不至于把标题写崩
def test_unknown_weight_falls_back_to_its_code():
    assert _render("inverse_vol").get_title() == (
        "Cumulative Returns of INVERSE_VOL Portfolios"
    )


def test_axis_labels_are_off_by_default():
    ax = _render()
    assert ax.get_xlabel() == ""
    assert ax.get_ylabel() == ""


def test_axis_labels_turn_on_by_flag_or_explicit_text():
    assert _render(show_xlabel=True).get_xlabel() == "Date"
    assert _render(ylabel="Cumulative Return").get_ylabel() == "Cumulative Return"


# 刻度一律去尾零：0.00→0、0.50→0.5、1.00→1
def test_ticks_drop_trailing_zeros():
    formatter = _render().yaxis.get_major_formatter()
    formatter.set_locs([0.0, 0.25, 0.5, 1.0])
    assert formatter(0.0) == "0"
    assert formatter(0.5).endswith("0.5")
    assert formatter(1.0).endswith("1")
    assert formatter(0.25).endswith("0.25")


# 分位色阶图的图例只报分位号与 H-L，不重复模型名
def test_gradient_legend_drops_the_signal_name():
    ax = _render(buckets=[*(str(i) for i in range(10)), "H-L"], color_mode="gradient")
    labels = [line.get_label() for line in ax.lines]
    assert labels[:3] == ["Decile 0", "Decile 1", "Decile 2"]
    assert labels[-1] == "H-L"


# 单信号图不必反复写模型名，多信号才需要它区分
def test_sole_signal_legend_drops_the_signal_name():
    ax = _render(buckets=["0", "H-L"])
    assert [line.get_label() for line in ax.lines] == ["0", "H-L"]


def test_multi_signal_legend_keeps_the_signal_name():
    ax = _render(buckets=["H-L"], signals=["S", "T"])
    assert [line.get_label() for line in ax.lines] == ["S H-L", "T H-L"]


def test_custom_legend_label_wins():
    ax = _render(buckets=["0"], legend_label="D{bucket} · {signal}")
    assert ax.lines[0].get_label() == "D0 · S"


def test_legend_columns_are_per_chart():
    assert _render(legend_ncol=2).get_legend()._ncols == 2


# 刻度字号固定放大，不跟着 style 走
def test_tick_fontsize_is_fixed():
    ax = _render()
    assert ax.yaxis.get_ticklabels()[0].get_fontsize() == TICK_FONTSIZE
    assert ax.xaxis.get_ticklabels()[0].get_fontsize() == TICK_FONTSIZE
    assert not hasattr(StyleSpec(), "tick_fontsize")


# 曲线之外不应多出那条基准横线
def test_baseline_is_not_drawn_by_default():
    assert len(_render().lines) == 1
    assert len(_render(show_baseline=True).lines) == 2


def test_legend_box_is_grey_edged_and_half_transparent_white():
    frame = _render().get_legend().get_frame()
    assert frame.get_edgecolor() == mpl.colors.to_rgba("#808080")
    assert frame.get_facecolor() == mpl.colors.to_rgba("#ffffff", 0.5)


def test_legend_sits_in_the_upper_left_by_default():
    assert _render().get_legend()._loc == Legend.codes["upper left"]
    assert _render(legend_loc="lower right").get_legend()._loc == Legend.codes["lower right"]


# 四个角以外的位置会挡住曲线，配置阶段就拦掉
def test_legend_loc_outside_the_four_corners_is_rejected():
    with pytest.raises(ConfigError):
        ChartSpec(name="curve", legend_loc="center")
    with pytest.raises(ConfigError):
        StyleSpec(legend_loc="best")


# 桶排序必须按数值，不能按字符串（否则 "10" 会排到 "2" 前面）
def test_bucket_order_is_numeric_not_lexical():
    assert bucket_rank("9") < bucket_rank("10")
    assert bucket_rank("H-L") == bucket_rank("REF") == float("inf")
    frame = pd.DataFrame({
        "bucket": ["H-L", "10", "2", "9", "REF", "0"],
        "weight": "EW",
    })
    assert list(sort_by_bucket(frame, ["weight"])["bucket"]) == [
        "0", "2", "9", "10", "H-L", "REF",
    ]


# 结果表先按 weight 分组，再按 bucket 升序
def test_summary_sorted_by_weight_then_bucket():
    frame = pd.DataFrame({
        "signal_model": "S",
        "weight": ["VW", "EW", "VW", "EW"],
        "bucket": ["H-L", "1", "0", "H-L"],
    })
    out = sort_by_bucket(frame, ["signal_model", "weight"])
    assert list(zip(out["weight"], out["bucket"])) == [
        ("EW", "1"), ("EW", "H-L"), ("VW", "0"), ("VW", "H-L"),
    ]


# ------------------------------------------------------- 内置 S&P 500 基准

# 基准跟随该图的加权方案：EW 组合对 EW 指数，VW 组合对 VW 指数
def test_benchmark_follows_the_weight_scheme():
    assert benchmark_label("EW") == "S&P 500 EW"
    assert benchmark_label("VW") == "S&P 500 VW"
    assert benchmark_label("sqrtvw") == "S&P 500 VW"   # 未登记方案退回市值加权
    axis = pd.DatetimeIndex(["2021-01-04", "2021-12-31"])
    assert (
        benchmark_curve(axis, "EW")["equity"].iloc[-1]
        != benchmark_curve(axis, "VW")["equity"].iloc[-1]
    )


# 策略对比图默认画基准
def test_benchmark_is_drawn_on_comparison_charts():
    ax = _render(show_benchmark=True)
    assert benchmark_label("EW") in [line.get_label() for line in ax.lines]


# 净值图已从包里移除，只保留累计对数收益一种线图
def test_equity_chart_is_no_longer_registered():
    from stockportfoliotoolkit.visualizer import CHARTS

    assert "equity" not in CHARTS
    assert CHARTS.names() == ["cumulative_log_return"]


# 颜色/线型硬编码：用户在 palette、reference_color 上怎么写都改不动
def test_benchmark_style_is_hardcoded_black():
    hostile = StyleSpec(
        palette={"S&P 500 EW": "#ff0000", "S&P 500 VW": "#ff0000"},
        reference_color="#ff0000",
        linewidth=9.9,
    )
    figure = build_chart("cumulative_log_return").render(
        _curves(), ChartSpec(name="curve"), hostile, "EW"
    )
    line = next(
        l for l in figure.axes[0].lines if l.get_label() == benchmark_label("EW")
    )
    assert line.get_color() == "#000000"
    assert line.get_linestyle() == "-"
    assert line.get_linewidth() == BENCHMARK_STYLE["linewidth"] != hostile.linewidth


def test_benchmark_style_mapping_is_immutable():
    with pytest.raises(TypeError):
        BENCHMARK_STYLE["color"] = "#ff0000"


def test_benchmark_can_be_switched_off_but_not_restyled():
    ax = _render(show_benchmark=False)
    assert benchmark_label("EW") not in [line.get_label() for line in ax.lines]
    assert not hasattr(StyleSpec(), "benchmark_color")


# 基准是买入持有后按图表日期轴取样，与调仓节奏无关
def test_benchmark_curve_is_buy_and_hold():
    daily = load_sp500_daily()
    axis = pd.DatetimeIndex(["2021-01-04", "2021-06-30", "2021-12-31"])
    curve = benchmark_curve(axis, "VW")
    window = daily[(daily["date"] > axis[0]) & (daily["date"] <= axis[-1])]
    assert curve["equity"].iloc[0] == pytest.approx(1.0)
    assert curve["equity"].iloc[-1] == pytest.approx(float((1 + window["vw_ret"]).prod()))
    assert np.allclose(curve["cum_log_ret"], np.log(curve["equity"]))


# 覆盖区间之外不外推：宁可断线，也不画一段假的水平线
def test_benchmark_does_not_extrapolate():
    curve = benchmark_curve(pd.DatetimeIndex(["2024-01-02", "2030-01-02"]), "VW")
    assert curve["equity"].iloc[0] == pytest.approx(1.0)
    assert np.isnan(curve["equity"].iloc[-1])
    assert benchmark_curve(pd.DatetimeIndex(["1980-01-02", "2000-01-03"]), "VW").empty


def test_packaged_benchmark_data_is_present_and_sane():
    daily = load_sp500_daily()
    assert len(daily) > 8000
    assert daily["date"].is_monotonic_increasing
    assert not daily["date"].duplicated().any()
    for column in ("ew_ret", "vw_ret"):
        assert daily[column].notna().all()
        assert daily[column].abs().max() < 0.5


# ----------------------------------------------------------- 多信号呈现

# gradient 的色阶被分位占满，多信号只能靠线型区分，否则两路信号完全撞车
def test_gradient_separates_signals_by_linestyle():
    lines = [(s, b) for s in ("MOM", "REV") for b in ("0", "1", "H-L")]
    styles = Palette(StyleSpec()).assign(lines, mode="gradient")
    assert styles[("MOM", "0")]["color"] == styles[("REV", "0")]["color"]  # 同分位同色
    assert styles[("MOM", "0")]["linestyle"] != styles[("REV", "0")]["linestyle"]
    assert styles[("MOM", "H-L")]["linestyle"] != styles[("REV", "H-L")]["linestyle"]


# 单信号 gradient 保持原样：实线 + "Decile n"
def test_gradient_single_signal_keeps_solid_lines():
    styles = Palette(StyleSpec()).assign(DECILES, mode="gradient")
    assert {s["linestyle"] for s in styles.values()} == {"-"}


def test_gradient_multi_signal_legend_carries_the_signal():
    ax = _render(buckets=["0", "1", "H-L"], signals=["S", "T"], color_mode="gradient")
    labels = [line.get_label() for line in ax.lines]
    assert labels == ["S D0", "S D1", "S H-L", "T D0", "T D1", "T H-L"]
    assert len(set(labels)) == len(labels)


# ------------------------------------------------- 分位图 vs 策略对比图

# 分位图在拆解单一策略，多一条 S&P 500 没有意义；策略对比图才需要基准
def test_decile_charts_drop_the_benchmark_by_default():
    decile = ChartSpec(name="decile_spread", color_mode="gradient")
    compare = ChartSpec(name="long_short")
    assert decile.is_decile_view and not compare.is_decile_view
    assert not decile.wants_benchmark()
    assert compare.wants_benchmark()
    ax = _render(buckets=["0", "1", "H-L"], color_mode="gradient", show_benchmark=None)
    assert not [l for l in ax.lines if "S&P 500" in str(l.get_label())]


# 分位图逐信号出图，策略对比图把所有信号叠在一张上
def test_split_by_signal_defaults_follow_the_chart_kind():
    assert ChartSpec(name="d", color_mode="gradient").wants_split_by_signal()
    assert not ChartSpec(name="ls").wants_split_by_signal()


# 显式设置永远压过自动判断
def test_explicit_flags_win_over_auto():
    spec = ChartSpec(name="d", color_mode="gradient", show_benchmark=True, split_by_signal=False)
    assert spec.wants_benchmark() and not spec.wants_split_by_signal()
    spec = ChartSpec(name="ls", show_benchmark=False, split_by_signal=True)
    assert not spec.wants_benchmark() and spec.wants_split_by_signal()
