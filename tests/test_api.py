# 门面 API：入参归一、默认值推导、出图落盘与反向导出
from __future__ import annotations

import warnings

import pandas as pd
import pytest

import alpholio as alp
from alpholio.config_schema import (
    ConfigError,
    HoldingPeriodWarning,
    SignalSpec,
)
from alpholio.contracts import CAP, CLOSE, ContractError
from alpholio.pipeline import run_pipeline
from alpholio.presets import chart_preset
from alpholio.settings import settings

HORIZON = 5


# settings 是进程级可变全局，用例间必须隔离，否则样式改动会渗到后续用例
@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    settings.reset()


@pytest.fixture
def flat_signals(signals) -> pd.DataFrame:
    """conftest 的信号夹具带 signal_model 列，门面按单路信号处理，这里去掉它"""
    return signals[["date", "id", "alpha"]].copy()


def _run(flat_signals, prices, **kwargs):
    return alp.backtest(
        signals=flat_signals, prices=prices, horizon=HORIZON,
        n_buckets=2, min_names=4, **kwargs
    )


# --------------------------------------------------------- 入参归一

def test_dataframe_and_file_paths_agree(tmp_path, flat_signals, prices):
    """内存直传与文件路径必须算出同一张指标表"""
    flat_signals.to_feather(tmp_path / "sig.feather")
    prices.to_feather(tmp_path / "px.feather")

    from_frame = _run(flat_signals, prices).summary()
    from_file = _run(str(tmp_path / "sig.feather"), str(tmp_path / "px.feather")).summary()
    pd.testing.assert_frame_equal(from_frame, from_file)


def test_column_names_are_auto_detected(flat_signals, prices):
    """列名已是契约名时不必写 column_map"""
    bt = _run(flat_signals, prices)
    assert bt.signal_names == ["signal"]
    assert not bt.returns.empty


def test_renamed_columns_need_an_explicit_map(flat_signals, prices):
    """自动识别只认契约同名列；对不上时报错并列出源列，不静默产出空表"""
    renamed = flat_signals.rename(columns={"date": "anchor", "id": "sym"})
    with pytest.raises(ContractError, match="缺少必需列"):
        _run(renamed, prices)

    bt = _run(renamed, prices, signal_columns={"date": "anchor", "id": "sym", "alpha": "alpha"})
    assert not bt.returns.empty


def test_multiple_signals_come_from_a_mapping(flat_signals, prices):
    other = flat_signals.assign(alpha=flat_signals["alpha"] * -1.0)
    bt = _run({"MOM": flat_signals, "REV": other}, prices)
    assert bt.signal_names == ["MOM", "REV"]


def test_unsupported_input_type_is_rejected(flat_signals, prices):
    with pytest.raises(ConfigError, match="只接受 DataFrame"):
        _run(flat_signals, 42)


def test_spec_objects_pass_through(tmp_path, flat_signals, prices):
    flat_signals.to_feather(tmp_path / "sig.feather")
    spec = SignalSpec(name="CUSTOM", path=str(tmp_path / "sig.feather"))
    assert _run(spec, prices).signal_names == ["CUSTOM"]


# --------------------------------------------------------- 默认值推导

def test_value_weighting_requires_cap(flat_signals, prices):
    """没有市值列时 vw 会产出整列 NaN，因此按数据决定 weights"""
    assert _run(flat_signals, prices).weights == ["EW", "VW"]
    assert _run(flat_signals, prices.drop(columns=[CAP])).weights == ["EW"]


def test_rebalance_freq_defaults_to_horizon(flat_signals, prices):
    """缺省取同值，使相邻持有窗口首尾相接，不触发重叠告警"""
    with warnings.catch_warnings():
        warnings.simplefilter("error", HoldingPeriodWarning)
        bt = _run(flat_signals, prices)
    assert bt.config.input.calendar.rebalance_freq == HORIZON


def test_mismatched_holding_days_still_warns(flat_signals, prices):
    """自动缺省不掩盖显式的口径不一致"""
    with pytest.warns(HoldingPeriodWarning):
        _run(flat_signals, prices, holding_days=HORIZON + 3)


def test_forward_return_source_follows_the_data(flat_signals, prices):
    """信号没有 fwd_ret 时由 close 推算"""
    assert _run(flat_signals, prices).config.engine.forward_return.source == "prices"


def test_self_supplied_returns_win_over_close(flat_signals, prices):
    """信号自带 fwd_ret 是明确算过实现收益的表示，优先于价格面板顺带提供的 close——
    取 close 会把那一列静默丢掉，两种口径在含分红的数据上能差出数量级。"""
    with_fwd = flat_signals.assign(fwd_ret=0.01)

    assert _run(with_fwd, prices).config.engine.forward_return.source == "signals"
    assert _run(with_fwd, prices.drop(columns=[CLOSE])).config.engine.forward_return.source == "signals"

    # 显式指定仍然说了算
    forced = _run(with_fwd, prices, forward_return_source="prices")
    assert forced.config.engine.forward_return.source == "prices"


def test_self_supplied_returns_are_actually_used(flat_signals, prices):
    """口径推导不只是改了配置字段：自带列必须真的进到结果里"""
    with_fwd = flat_signals.assign(fwd_ret=0.02)
    hl = _run(with_fwd, prices).summary(bucket="0", weight="EW")
    assert hl["ann_ret"].notna().all()
    # 每期收益恒为 0.02，分位内等权平均后仍是 0.02
    returns = _run(with_fwd, prices).returns
    assert returns.query("bucket == '0' and weight == 'EW'")["ret"].round(6).eq(0.02).all()


def test_misspelled_parameter_is_rejected(flat_signals, prices):
    with pytest.raises(TypeError, match="n_bucket"):
        _run(flat_signals, prices, n_bucket=5)


# --------------------------------------------------------- 结果对象

def test_intermediates_are_reachable(flat_signals, prices):
    bt = _run(flat_signals, prices)
    for frame in (bt.returns, bt.curves, bt.members, bt.aligned):
        assert isinstance(frame, pd.DataFrame) and not frame.empty


def test_summary_filters_by_bucket_and_weight(flat_signals, prices):
    bt = _run(flat_signals, prices)
    assert set(bt.summary(bucket="H-L")["bucket"]) == {"H-L"}
    assert set(bt.summary(weight="EW")["weight"]) == {"EW"}


def test_repr_carries_the_headline_metrics(flat_signals, prices):
    text = repr(_run(flat_signals, prices))
    assert "BacktestResult" in text and "H-L" in text


# --------------------------------------------------------- 出图

def test_plot_returns_a_figure(flat_signals, prices):
    fig = _run(flat_signals, prices).plot("long_short")
    assert fig.axes and fig.axes[0].lines


def test_unknown_preset_lists_the_available_ones(flat_signals, prices):
    with pytest.raises(ValueError, match="long_short"):
        _run(flat_signals, prices).plot("nope")


def test_unknown_weight_is_rejected(flat_signals, prices):
    with pytest.raises(ConfigError, match="未知的加权方案"):
        _run(flat_signals, prices).plot(weight="ZZ")


def test_decile_preset_follows_n_buckets():
    """分位桶列表跟随 n_buckets，不会与配置脱节"""
    assert chart_preset("deciles", 5).buckets == ["0", "1", "2", "3", "4", "H-L"]
    assert chart_preset("deciles", 10).buckets[-1] == "H-L"


def test_global_style_applies_and_resets(flat_signals, prices):
    bt = _run(flat_signals, prices)
    settings.style.figsize = [4.0, 3.0]
    assert tuple(bt.plot("long_short").get_size_inches()) == (4.0, 3.0)

    settings.reset()
    assert tuple(bt.plot("long_short").get_size_inches()) != (4.0, 3.0)


def test_per_chart_override_beats_the_preset(flat_signals, prices):
    bt = _run(flat_signals, prices)
    assert bt.plot("long_short").axes[0].get_title()
    assert bt.plot("long_short", show_title=False).axes[0].get_title() == ""


# --------------------------------------------------------- 落盘与导出

def test_save_writes_charts_and_tables(tmp_path, flat_signals, prices):
    files = _run(flat_signals, prices).save(tmp_path / "out")
    names = {p.name for p in files}
    assert any(n.endswith(".png") for n in names)
    assert "metrics.csv" in names and "summary_metrics.csv" in names


def test_save_without_a_target_explains_why(flat_signals, prices):
    """内存输入没有数据文件可作落点锚，不猜测目录"""
    with pytest.raises(ConfigError, match="未指定落盘目录"):
        _run(flat_signals, prices).save()


def test_to_config_needs_a_data_dir_for_in_memory_input(tmp_path, flat_signals, prices):
    with pytest.raises(ConfigError, match="内存 DataFrame"):
        _run(flat_signals, prices).to_config(tmp_path / "cfg")


def test_exported_config_reproduces_the_same_numbers(tmp_path, flat_signals, prices):
    """反向导出的 JSON 经 run_pipeline 重跑，指标须与原结果逐值一致——
    这同时验证门面与配置两条路径的口径相同。"""
    original = _run(flat_signals, prices, output_dir=str(tmp_path / "out"))
    original.to_config(tmp_path / "cfg", data_dir=tmp_path / "data")

    replayed = run_pipeline(tmp_path / "cfg", render=False)
    pd.testing.assert_frame_equal(
        original.summary(), replayed.analysis.summary.reset_index(drop=True)
    )


def test_exported_config_is_valid_json(tmp_path, flat_signals, prices):
    """导出的四份配置须能被各自的 from_file 读回，不含无法序列化的字段"""
    import json

    paths = _run(flat_signals, prices).to_config(tmp_path / "cfg", data_dir=tmp_path / "d")
    assert {p.name for p in paths} == {
        "input.json", "engine.json", "analyzer.json", "visualizer.json"
    }
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "frame" not in json.dumps(payload)
