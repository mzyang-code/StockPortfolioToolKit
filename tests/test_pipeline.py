# 契约、配置校验与端到端流水线
from __future__ import annotations

import pandas as pd
import pytest

from stockportfoliotoolkit import run_pipeline, to_legacy_wide
from stockportfoliotoolkit.config import ConfigError, EngineConfig
from stockportfoliotoolkit.contracts import ContractError, InputBundle


def test_unknown_config_key_is_rejected():
    with pytest.raises(ConfigError, match="未知配置项"):
        EngineConfig.from_dict({"n_bukets": 10})


def test_nested_config_validated():
    with pytest.raises(ConfigError):
        EngineConfig.from_dict({"long_short": {"enabl": True}})


def test_bundle_requires_contract_columns(prices, trading_days):
    with pytest.raises(ContractError, match="缺少列"):
        InputBundle(
            signals=pd.DataFrame({"date": [], "id": []}),
            prices=prices,
            calendar=trading_days,
        )


def test_legacy_wide_roundtrip():
    returns = pd.DataFrame({
        "date": [pd.Timestamp("2020-01-01")] * 2,
        "signal_model": "S", "bucket": "H-L", "weight": ["EW", "VW"],
        "ret": [0.1, 0.2], "count": 4,
    })
    wide = to_legacy_wide(returns)
    # legacy 侧保持 stock_rag_v1 的列名，不跟随包内改名
    assert list(wide.columns) == ["anchor_date", "signal", "decile", "ew_ret", "vw_ret", "n_names"]
    assert wide.iloc[0]["ew_ret"] == pytest.approx(0.1)


def test_end_to_end(config_dir):
    result = run_pipeline(config_dir)
    assert not result.analysis.summary.empty
    assert {"H-L", "REF"}.issubset(set(result.engine.returns["bucket"]))
    written = {path.name for path in result.outputs}
    assert {"curve_ew.png", "metrics.csv", "summary_metrics.csv"}.issubset(written)
    assert all(path.exists() and path.stat().st_size > 0 for path in result.outputs)


def test_pipeline_can_skip_rendering(config_dir):
    assert run_pipeline(config_dir, render=False).outputs == []


# CLI 单独走一条 import 路径，容易在重构时漏改
def test_cli_runs(config_dir, capsys):
    from stockportfoliotoolkit.cli import main

    assert main(["run", "--config-dir", str(config_dir)]) == 0
    assert "wrote" in capsys.readouterr().out
