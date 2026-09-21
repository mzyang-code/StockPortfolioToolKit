# 月度口径：日历落月末、前视收益与市值按自然月对齐、年化基数取 12
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

import stockportfoliotoolkit as spt
from stockportfoliotoolkit.config_schema import (
    CalendarSpec,
    ConfigError,
    EngineConfig,
    ForwardReturnSpec,
    HoldingPeriodWarning,
    InputConfig,
    PriceSpec,
    SignalSpec,
)
from stockportfoliotoolkit.contracts import ContractError, InputBundle
from stockportfoliotoolkit.engine import PortfolioEngine, forward_returns
from stockportfoliotoolkit.frequency import MONTHLY, month_key, resolve
from stockportfoliotoolkit.input import InputProcessor

from conftest import INTRA_MONTH_CAP_FACTOR, N_ASSETS, monthly_growth


def _input_cfg(signals, prices, **calendar) -> InputConfig:
    return InputConfig(
        prices=PriceSpec(frame=prices),
        signals=[SignalSpec(name="SYN", frame=signals)],
        calendar=CalendarSpec(**{"rebalance_freq": 1, **calendar}),
        frequency=MONTHLY,
    )


def _engine_cfg(**kwargs) -> EngineConfig:
    defaults = {
        "n_buckets": 2,
        "min_names": 4,
        "weights": ["ew"],
        "forward_return": ForwardReturnSpec(horizon=1),
    }
    return EngineConfig(**{**defaults, **kwargs})


def _bundle(signals, prices, **calendar) -> InputBundle:
    return InputProcessor(_input_cfg(signals, prices, **calendar)).run()


# --------------------------------------------------------- 调仓日历

def test_calendar_falls_on_month_ends(daily_signals_over_months, intramonth_prices, month_ends):
    """信号每个交易日都有时，月度口径把日历落到每月最后一个可用日期"""
    bundle = _bundle(daily_signals_over_months, intramonth_prices)
    pd.testing.assert_index_equal(pd.DatetimeIndex(bundle.calendar), month_ends)
    assert bundle.frequency == MONTHLY
    assert bundle.meta["calendar"]["unit"] == "月"


def test_calendar_keeps_native_monthly_dates(monthly_signals, monthly_prices, month_ends):
    """面板本来就是月频时日历原样保留，不因为抽稀再掉一半"""
    bundle = _bundle(monthly_signals, monthly_prices)
    pd.testing.assert_index_equal(pd.DatetimeIndex(bundle.calendar), month_ends)
    assert bundle.meta["calendar"]["native_stride"] == 1
    assert bundle.meta["calendar"]["applied_stride"] == 1


def test_rebalance_freq_counts_calendar_months(daily_signals_over_months, intramonth_prices, month_ends):
    """rebalance_freq 在月度口径下数的是自然月，不是交易日"""
    bundle = _bundle(daily_signals_over_months, intramonth_prices, rebalance_freq=3)
    pd.testing.assert_index_equal(pd.DatetimeIndex(bundle.calendar), month_ends[::3])
    assert np.all(np.diff(month_key(bundle.calendar)) == 3)


def test_midmonth_signals_anchor_inside_the_month(midmonth_signals, intramonth_prices, month_thirds):
    """信号只在月内某天落盘时，锚点就是那一天——日历不会被强行挪到月末"""
    bundle = _bundle(midmonth_signals, intramonth_prices)
    pd.testing.assert_index_equal(pd.DatetimeIndex(bundle.calendar), month_thirds)


# --------------------------------------------------------- 前视收益

def test_forward_return_spans_calendar_months(intramonth_prices, month_ends):
    """日频面板下仍按「月末 close → h 个月后月末 close」测量，月内价格不参与"""
    fwd = forward_returns(intramonth_prices, holding_days=1, frequency=MONTHLY)
    first = fwd[fwd["id"] == "A0"]
    # 每资产每月一行，日期落在月末
    assert len(first) == len(month_ends)
    pd.testing.assert_index_equal(pd.DatetimeIndex(first["date"].to_numpy()), month_ends)
    assert first["fwd_ret"].iloc[0] == pytest.approx(monthly_growth(0) - 1.0)
    assert np.isnan(first["fwd_ret"].iloc[-1])  # 末月没有下一个月

    two = forward_returns(intramonth_prices, holding_days=2, frequency=MONTHLY)
    assert two[two["id"] == "A3"]["fwd_ret"].iloc[0] == pytest.approx(monthly_growth(3) ** 2 - 1.0)


def test_missing_month_breaks_the_window(monthly_prices, month_ends):
    """缺月不能被悄悄跨过去：缺口前一期只能是 NaN，而不是够到两个月后"""
    dropped = monthly_prices[
        ~((monthly_prices["id"] == "A0") & (monthly_prices["date"] == month_ends[5]))
    ]
    fwd = forward_returns(dropped, holding_days=1, frequency=MONTHLY)
    a0 = fwd[fwd["id"] == "A0"].set_index("date")["fwd_ret"]
    assert np.isnan(a0.loc[month_ends[4]])
    assert a0.loc[month_ends[3]] == pytest.approx(monthly_growth(0) - 1.0)
    # 其他资产不受影响
    assert fwd[fwd["id"] == "A1"]["fwd_ret"].iloc[4] == pytest.approx(monthly_growth(1) - 1.0)


def test_panel_aligns_signals_and_prices_by_month(midmonth_signals, intramonth_prices):
    """锚点在月内、价格月末在另一天，两边按自然月对齐仍取得到数"""
    bundle = _bundle(midmonth_signals, intramonth_prices)
    aligned = PortfolioEngine(_engine_cfg()).run(bundle).aligned
    a0 = aligned[aligned["id"] == "A0"]
    assert not a0.empty
    assert a0["fwd_ret"].iloc[0] == pytest.approx(monthly_growth(0) - 1.0)


def test_caps_come_from_month_end(midmonth_signals, intramonth_prices):
    """市值取当月最后一个可用值：月内那些放大 10 倍的市值不该被取到"""
    bundle = _bundle(midmonth_signals, intramonth_prices)
    aligned = PortfolioEngine(_engine_cfg(weights=["ew", "vw"])).run(bundle).aligned
    caps = aligned[aligned["id"] == "A0"]["cap"].dropna().unique()
    assert caps == pytest.approx([10.0])
    assert not np.isclose(caps[0], 10.0 * INTRA_MONTH_CAP_FACTOR)


# --------------------------------------------------------- 年化因子

def _summary_meta(signals, prices, **kwargs):
    bt = spt.backtest(
        signals=signals[["date", "id", "alpha"]], prices=prices,
        horizon=1, frequency=MONTHLY, n_buckets=2, min_names=4, **kwargs
    )
    return bt


def test_annualization_base_is_twelve(monthly_signals, monthly_prices):
    """月度口径下年化按每年 12 期折算，不再需要手写 periods_per_year"""
    bt = _summary_meta(monthly_signals, monthly_prices)
    assert bt.analysis.meta["periods_per_year"] == pytest.approx(12.0)
    assert bt.analysis.meta["frequency"] == MONTHLY


def test_annualization_follows_holding_days(monthly_signals, monthly_prices):
    """holding_days 在月度口径下数的是月：每年 12/3 = 4 期"""
    with pytest.warns(HoldingPeriodWarning):
        bt = _summary_meta(monthly_signals, monthly_prices, holding_days=3)
    assert bt.analysis.meta["periods_per_year"] == pytest.approx(4.0)


def test_explicit_periods_per_year_still_wins(monthly_signals, monthly_prices):
    bt = _summary_meta(monthly_signals, monthly_prices, periods_per_year=6.0)
    assert bt.analysis.meta["periods_per_year"] == pytest.approx(6.0)


def test_daily_annualization_is_unchanged(signals, prices):
    """日频路径逐值不变：仍是 trading_days_per_year / holding_days"""
    bt = spt.backtest(
        signals=signals[["date", "id", "alpha"]], prices=prices,
        horizon=5, n_buckets=2, min_names=4,
    )
    assert bt.analysis.meta["periods_per_year"] == pytest.approx(252.0 / 5)
    assert bt.analysis.meta["frequency"] == "daily"


def test_annualized_return_matches_hand_computation(monthly_signals, monthly_prices):
    """每期收益已知，年化收益 = 均值 × 12，可手算核对"""
    bt = _summary_meta(monthly_signals, monthly_prices)
    row = bt.summary(bucket="1", weight="EW").iloc[0]
    # 高桶是 A4..A7，每月收益为各自的固定月涨幅，等权平均
    expected = np.mean([monthly_growth(i) - 1.0 for i in range(N_ASSETS // 2, N_ASSETS)])
    assert row["ann_ret"] == pytest.approx(expected * 12.0)


# --------------------------------------------------------- 口径告警

def test_overlap_warning_counts_months(daily_signals_over_months, intramonth_prices):
    """调仓间隔 2 个月、测量期 1 个月：告警须用「月」而不是「交易日」"""
    bundle = _bundle(daily_signals_over_months, intramonth_prices, rebalance_freq=2)
    with pytest.warns(HoldingPeriodWarning, match="2 个月") as caught:
        PortfolioEngine(_engine_cfg()).run(bundle)
    assert "交易日" not in str(caught[0].message)


def test_matching_monthly_cadence_is_silent(monthly_signals, monthly_prices):
    bundle = _bundle(monthly_signals, monthly_prices)
    with warnings.catch_warnings():
        warnings.simplefilter("error", HoldingPeriodWarning)
        PortfolioEngine(_engine_cfg()).run(bundle)


# --------------------------------------------------------- 外部基准

def _bundle_with_reference(signals, prices, reference) -> InputBundle:
    bundle = _bundle(signals, prices)
    return InputBundle(
        signals=bundle.signals, prices=bundle.prices, calendar=bundle.calendar,
        references=reference, meta=bundle.meta, frequency=MONTHLY,
    )


def _reference_returns(bundle, **engine_kwargs) -> pd.Series:
    result = PortfolioEngine(_engine_cfg(include_references=True, **engine_kwargs)).run(bundle)
    ref = result.returns.query("bucket == 'REF'")
    return ref.set_index("date")["ret"]


def test_daily_reference_compounds_over_a_calendar_month(
    monthly_signals, monthly_prices, daily_reference, business_days, month_ends
):
    """日频基准在「锚点次日 → 目标月月末」上复利，窗口即整个下一自然月"""
    series = _reference_returns(_bundle_with_reference(monthly_signals, monthly_prices, daily_reference))
    days_in_february = int(((business_days > month_ends[0]) & (business_days <= month_ends[1])).sum())
    assert series.loc[month_ends[0]] == pytest.approx(1.002 ** days_in_february - 1.0)
    # 末期窗口没有数据，不产出截断收益
    assert month_ends[-1] not in series.index


def test_reference_lag_zero_includes_the_anchor_day(
    monthly_signals, monthly_prices, daily_reference, business_days, month_ends
):
    bundle = _bundle_with_reference(monthly_signals, monthly_prices, daily_reference)
    series = _reference_returns(bundle, reference_lag=0)
    window = int(((business_days >= month_ends[0]) & (business_days < month_ends[1])).sum())
    assert series.loc[month_ends[0]] == pytest.approx(1.002 ** window - 1.0)


def test_reference_window_starts_at_the_anchor_month_end(
    midmonth_signals, intramonth_prices, daily_reference, business_days, month_ends
):
    """锚点落在月内时，基准窗口仍是一个自然月——从锚点所在月的月末起算。

    从锚点当天起算会把当月剩下的行情多算进来，一期变成近两个月，而组合那一期测的是
    月末收盘到月末收盘。"""
    bundle = _bundle(midmonth_signals, intramonth_prices)
    bundle = InputBundle(
        signals=bundle.signals, prices=bundle.prices, calendar=bundle.calendar,
        references=daily_reference, meta=bundle.meta, frequency=MONTHLY,
    )
    series = _reference_returns(bundle)
    anchor = bundle.calendar[0]  # 1 月内第三个交易日
    window = int(((business_days > month_ends[0]) & (business_days <= month_ends[1])).sum())
    assert series.loc[anchor] == pytest.approx(1.002 ** window - 1.0)
    # 逐期反解窗口长度：每期恰好是下一个自然月的全部交易日，不随锚点在月内的位置漂移
    lengths = np.log1p(series.to_numpy()) / np.log(1.002)
    per_month = pd.Series(1, index=business_days).groupby(business_days.to_period("M")).sum()
    assert lengths == pytest.approx(per_month.to_numpy()[1: len(lengths) + 1])


def test_reference_lag_beyond_one_is_rejected(monthly_signals, monthly_prices, daily_reference):
    """自然月窗口没有「第 2 个交易日开始」这回事，不静默当成 1 处理"""
    bundle = _bundle_with_reference(monthly_signals, monthly_prices, daily_reference)
    with pytest.raises(ContractError, match="reference_lag"):
        _reference_returns(bundle, reference_lag=2)


def test_period_reference_aligns_by_month(monthly_signals, monthly_prices, month_ends, business_days):
    """已是月度收益的基准按自然月对齐：观测日与锚点不是同一天也能对上"""
    offbeat = pd.DataFrame({
        "date": month_ends - pd.Timedelta(days=3),
        "name": "BENCH",
        "ret": 0.01,
        "frequency": "period",
    })
    bundle = _bundle_with_reference(monthly_signals, monthly_prices, offbeat)
    series = _reference_returns(bundle)
    assert len(series) == len(month_ends)
    assert series.round(6).eq(0.01).all()


# --------------------------------------------------------- 配置校验与端到端

def test_unknown_frequency_is_rejected_in_config():
    with pytest.raises(ConfigError, match="input.frequency"):
        InputConfig.from_dict({
            "prices": {"path": "p.feather"},
            "signals": [{"name": "S", "path": "s.feather"}],
            "frequency": "weekly",
        })


def test_unknown_frequency_is_rejected_in_bundle(monthly_signals, monthly_prices):
    with pytest.raises(ContractError, match="weekly"):
        InputBundle(
            signals=monthly_signals,
            prices=monthly_prices.assign(close=1.0),
            calendar=pd.DatetimeIndex([pd.Timestamp("2019-01-31")]),
            frequency="weekly",
        )


def test_frequency_resolution_is_case_insensitive():
    assert resolve("Monthly").is_monthly
    assert resolve(resolve(MONTHLY)) is resolve(MONTHLY)


def test_backtest_facade_runs_monthly(monthly_signals, monthly_prices):
    bt = _summary_meta(monthly_signals, monthly_prices)
    assert bt.config.input.frequency == MONTHLY
    assert not bt.summary(bucket="H-L").empty
    assert bt.meta["periods"] == 23  # 24 个月，末月无前视收益


def test_exported_config_keeps_the_frequency(tmp_path, monthly_signals, monthly_prices):
    """月度口径必须能随配置归档：导出再重跑，指标逐值一致"""
    from stockportfoliotoolkit.pipeline import run_pipeline

    original = _summary_meta(monthly_signals, monthly_prices)
    original.to_config(tmp_path / "cfg", data_dir=tmp_path / "data")

    import json

    payload = json.loads((tmp_path / "cfg" / "input.json").read_text(encoding="utf-8"))
    assert payload["frequency"] == MONTHLY

    replayed = run_pipeline(tmp_path / "cfg", render=False)
    pd.testing.assert_frame_equal(
        original.summary(), replayed.analysis.summary.reset_index(drop=True)
    )
