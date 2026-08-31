# Engine：分桶、三种加权、多空、前视收益、基准复利
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockportfoliotoolkit.config_schema import EngineConfig, ForwardReturnSpec
from stockportfoliotoolkit.contracts import ContractError
from stockportfoliotoolkit.engine import (
    PortfolioEngine,
    assign_buckets,
    bucket_returns,
    forward_returns,
)
from stockportfoliotoolkit.engine.weighting import (
    CapWeighter,
    EqualWeighter,
    build_weighter,
)


def _frame(caps, rets):
    return pd.DataFrame({"cap": caps, "fwd_ret": rets, "id": list("abcd")[: len(caps)]})


def test_equal_weights_sum_to_one():
    w = EqualWeighter().weights(_frame([1.0, 2.0, 3.0], [0.1, 0.2, 0.3]))
    assert np.allclose(w, 1 / 3)


# 缺市值的成分权重记 0，其余重新归一
def test_cap_weights_drop_missing():
    w = CapWeighter().weights(_frame([1.0, np.nan, 3.0], [0.1, 0.2, 0.3]))
    assert np.allclose(w, [0.25, 0.0, 0.75])
    assert CapWeighter().weights(_frame([0.0, 0.0], [0.1, 0.2])) is None


# 负市值同样记 0：不裁负值会让权重出现杠杆与反向暴露
def test_cap_weights_drop_non_positive():
    w = CapWeighter().weights(_frame([-10.0, 20.0], [0.1, 0.2]))
    assert np.allclose(w, [0.0, 1.0])
    assert CapWeighter().weights(_frame([-1.0, -2.0], [0.1, 0.2])) is None


def test_logvw_is_no_longer_registered():
    from stockportfoliotoolkit.engine import WEIGHTERS

    assert "logvw" not in WEIGHTERS
    assert WEIGHTERS.names() == ["ew", "vw"]


def test_forward_return_is_pure_price(prices):
    fwd = forward_returns(prices, holding_days=5)
    first = fwd[(fwd["id"] == "A0")].iloc[0]["fwd_ret"]
    assert first == pytest.approx(1.001 ** 5 - 1)


def test_buckets_respect_min_names(signals):
    panel = signals.rename(columns={"alpha": "alpha"}).assign(fwd_ret=0.0, cap=1.0)
    assert assign_buckets(panel, n_buckets=2, min_names=4).empty is False
    assert assign_buckets(panel, n_buckets=2, min_names=99).empty


def test_bucket_returns_match_hand_computation():
    panel = pd.DataFrame({
        "date": pd.Timestamp("2020-01-01"),
        "signal_model": "S",
        "bucket": ["0", "0", "1", "1"],
        "id": list("abcd"),
        "alpha": [1.0, 2.0, 3.0, 4.0],
        "fwd_ret": [0.1, 0.2, 0.3, 0.4],
        "cap": [1.0, 1.0, 1.0, 3.0],
    })
    out = bucket_returns(panel, [EqualWeighter(), CapWeighter()])
    got = out.set_index(["bucket", "weight"])["ret"]
    assert got[("0", "EW")] == pytest.approx(0.15)
    assert got[("1", "EW")] == pytest.approx(0.35)
    assert got[("1", "VW")] == pytest.approx((0.3 + 3 * 0.4) / 4)


def test_long_short_is_top_minus_bottom(bundle):
    cfg = EngineConfig(n_buckets=2, min_names=4, weights=["ew"], forward_return=ForwardReturnSpec(horizon=5))
    result = PortfolioEngine(cfg).run(bundle)
    wide = result.returns.pivot_table(index="date", columns="bucket", values="ret")
    assert np.allclose(wide["H-L"], wide["1"] - wide["0"], equal_nan=True)


# reverse 打开后多空腿整体反号
def test_long_short_reverse(bundle):
    cfg = EngineConfig(n_buckets=2, min_names=4, weights=["ew"], forward_return=ForwardReturnSpec(horizon=5))
    cfg.long_short.reverse = True
    wide = PortfolioEngine(cfg).run(bundle).returns.pivot_table(
        index="date", columns="bucket", values="ret"
    )
    assert np.allclose(wide["H-L"], wide["0"] - wide["1"], equal_nan=True)


# 日频基准按 [锚点+lag, +lag+持有期) 复利
def test_reference_compounding(bundle):
    cfg = EngineConfig(n_buckets=2, min_names=4, weights=["ew"], forward_return=ForwardReturnSpec(horizon=5))
    ref = PortfolioEngine(cfg).run(bundle).returns.query("bucket == 'REF'")
    assert ref["ret"].dropna().iloc[0] == pytest.approx(1.002 ** 5 - 1)


def test_unknown_weighter_is_rejected():
    with pytest.raises(KeyError):
        build_weighter("no_such_scheme")


def test_empty_weights_rejected():
    with pytest.raises(ContractError):
        PortfolioEngine(
            EngineConfig(weights=[], forward_return=ForwardReturnSpec(horizon=5))
        )
