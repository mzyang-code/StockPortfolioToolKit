# Analyzer：指标数学、换手率、IC、波动率缩放
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockportfoliotoolkit.analyzer import Analyzer, compute_ic, compute_turnover
from stockportfoliotoolkit.analyzer.curves import build_curves, vol_rescale_to_reference
from stockportfoliotoolkit.analyzer.metrics import MetricContext, build_metric
from stockportfoliotoolkit.config_schema import AnalyzerConfig, EngineConfig, ForwardReturnSpec
from stockportfoliotoolkit.contracts import ContractError
from stockportfoliotoolkit.engine import PortfolioEngine

CTX = MetricContext(periods_per_year=12.0)


def test_annualization_and_sharpe():
    rets = np.array([0.01, 0.02, 0.03, 0.02])
    ann_ret = build_metric("ann_ret").compute(rets, CTX)
    ann_vol = build_metric("ann_vol").compute(rets, CTX)
    assert ann_ret == pytest.approx(rets.mean() * 12)
    assert ann_vol == pytest.approx(rets.std(ddof=1) * np.sqrt(12))
    assert build_metric("sharpe").compute(rets, CTX) == pytest.approx(ann_ret / ann_vol)


def test_equity_and_drawdown():
    rets = np.array([0.5, -0.5, 0.2])
    assert build_metric("total_equity").compute(rets, CTX) == pytest.approx(1.5 * 0.5 * 1.2)
    assert build_metric("max_drawdown").compute(rets, CTX) == pytest.approx(0.75 / 1.5 - 1)


# 相邻两期成分的 Jaccard 距离
def test_turnover_jaccard():
    members = pd.DataFrame({
        "date": [pd.Timestamp("2020-01-01")] * 2 + [pd.Timestamp("2020-01-02")] * 2,
        "signal_model": "S",
        "id": ["a", "b", "b", "c"],
        "bucket": ["0", "0", "0", "0"],
    })
    out = compute_turnover(members)
    assert np.isnan(out.iloc[0]["turnover"])  # 首期无前值
    assert out.iloc[1]["turnover"] == pytest.approx(1 - 1 / 3)


def test_ic_is_spearman():
    aligned = pd.DataFrame({
        "date": pd.Timestamp("2020-01-01"),
        "signal_model": "S",
        "id": list("abcd"),
        "alpha": [1.0, 2.0, 3.0, 4.0],
        "fwd_ret": [0.1, 0.4, 0.2, 0.3],
        "cap": 1.0,
    })
    ic = compute_ic(aligned, min_names=4).iloc[0]["ic"]
    expected = pd.Series([1, 2, 3, 4]).corr(pd.Series([1, 4, 2, 3]), method="spearman")
    assert ic == pytest.approx(expected)
    assert np.isnan(compute_ic(aligned, min_names=99).iloc[0]["ic"])


def test_curves_start_from_shared_origin():
    returns = pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=3),
        "signal_model": "S", "bucket": "H-L", "weight": "EW",
        "ret": [0.1, -0.1, 0.2], "count": 4,
    })
    curve = build_curves(returns)
    assert curve.iloc[0]["equity"] == 1.0 and curve.iloc[0]["cum_log_ret"] == 0.0
    assert curve.iloc[-1]["equity"] == pytest.approx(1.1 * 0.9 * 1.2)
    assert curve.iloc[-1]["cum_log_ret"] == pytest.approx(np.log(1.1 * 0.9 * 1.2))


# 缩放后波动率对齐基准，且基准自身不变
def test_vol_rescale_matches_reference():
    dates = pd.bdate_range("2020-01-01", periods=30)
    returns = pd.concat([
        pd.DataFrame({"date": dates, "signal_model": "S", "bucket": "H-L", "weight": "EW",
                      "ret": np.linspace(-0.04, 0.06, 30), "count": 4}),
        pd.DataFrame({"date": dates, "signal_model": "B", "bucket": "REF", "weight": "EW",
                      "ret": np.linspace(-0.01, 0.02, 30), "count": 0}),
    ], ignore_index=True)
    scaled = vol_rescale_to_reference(returns, "B")
    std = scaled.groupby("signal_model")["ret"].std(ddof=1)
    assert std["S"] == pytest.approx(std["B"])
    assert np.allclose(
        scaled.query("signal_model == 'B'")["ret"], returns.query("signal_model == 'B'")["ret"]
    )


def _engine(bundle):
    return PortfolioEngine(
        EngineConfig(n_buckets=2, min_names=4, weights=["ew"], forward_return=ForwardReturnSpec(horizon=5))
    ).run(bundle)


# 默认关：产物里不出现口径列，年化因子由持有期推导
def test_vol_rescale_off_by_default(bundle):
    analysis = Analyzer(AnalyzerConfig()).run(_engine(bundle))
    assert "variant" not in analysis.summary.columns
    assert "variant" not in analysis.curves.columns
    assert analysis.meta["vol_rescaled"] is False
    assert analysis.meta["periods_per_year"] == pytest.approx(252 / 5)


# 打开后仍是单一口径，只是换成缩放后的收益（缩放数学见上一个用例）
def test_vol_rescale_switch_stays_single_variant(bundle):
    cfg = AnalyzerConfig()
    cfg.vol_rescale.enabled = True
    cfg.vol_rescale.reference = "BENCH"
    on = Analyzer(cfg).run(_engine(bundle))

    assert "variant" not in on.summary.columns
    assert "variant" not in on.curves.columns
    assert on.meta["vol_rescaled"] is True
    assert on.meta["vol_rescale_reference"] == "BENCH"


def test_vol_rescale_requires_reference(bundle):
    cfg = AnalyzerConfig()
    cfg.vol_rescale.enabled = True
    with pytest.raises(ContractError, match="reference"):
        Analyzer(cfg).run(_engine(bundle))
