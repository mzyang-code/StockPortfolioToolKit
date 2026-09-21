# 契约、配置校验与端到端流水线
from __future__ import annotations

import json
import warnings
from dataclasses import replace

import pandas as pd
import pytest

from alpholio import run_pipeline, to_legacy_wide
from alpholio.config_schema import (
    ConfigError,
    EngineConfig,
    ForwardReturnSpec,
    HoldingPeriodWarning,
)
from alpholio.contracts import ContractError, InputBundle
from alpholio.engine import PortfolioEngine


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
    from alpholio.cli import main

    assert main(["run", "--config-dir", str(config_dir)]) == 0
    assert "wrote" in capsys.readouterr().out


# ------------------------------------- forward_return 必填 / holding_days 继承

def test_forward_return_horizon_is_required():
    with pytest.raises(ConfigError, match="forward_return.horizon"):
        EngineConfig.from_dict({"n_buckets": 10})
    with pytest.raises(ConfigError, match="forward_return.horizon"):
        EngineConfig.from_dict({"forward_return": {"source": "prices"}})


def test_holding_days_inherits_forward_return_horizon():
    cfg = EngineConfig.from_dict({"forward_return": {"horizon": 12}})
    assert cfg.holding_days == 12
    # 直接构造走同一条校验路径
    assert EngineConfig(forward_return=ForwardReturnSpec(horizon=7)).holding_days == 7


# 显式指定且相等：不该有任何噪音
def test_matching_holding_days_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert EngineConfig.from_dict(
            {"holding_days": 5, "forward_return": {"horizon": 5}}
        ).holding_days == 5


# 不一致：告警但不中断，配置照常可用
def test_mismatched_holding_days_warns_without_raising():
    with pytest.warns(HoldingPeriodWarning, match="不一致"):
        cfg = EngineConfig.from_dict(
            {"holding_days": 21, "forward_return": {"horizon": 5}}
        )
    assert cfg.holding_days == 21 and cfg.forward_return.horizon == 5


def test_invalid_horizon_is_rejected():
    with pytest.raises(ConfigError, match="horizon"):
        EngineConfig.from_dict({"forward_return": {"horizon": 0}})
    with pytest.raises(ConfigError, match="holding_days"):
        EngineConfig.from_dict({"holding_days": 0, "forward_return": {"horizon": 5}})


# 调仓间隔与测量期不等 → 重叠/缺口告警，但结果照常产出
def test_overlapping_holding_windows_warn(bundle):
    cfg = EngineConfig(
        n_buckets=2, min_names=4, weights=["ew"], forward_return=ForwardReturnSpec(horizon=5)
    )
    dense = replace(bundle, calendar=bundle.prices["date"].drop_duplicates().sort_values())
    with pytest.warns(HoldingPeriodWarning, match="重叠"):
        PortfolioEngine(cfg).run(dense)


# ------------------------------------------------- 产物默认落点

# output_dir 留空 → 落到信号文件同级的 outputs/，图和表平铺在同一层
def test_outputs_default_next_to_the_signal_data(config_dir):
    cfg = json.loads((config_dir / "visualizer.json").read_text())
    cfg.pop("output_dir", None)
    (config_dir / "visualizer.json").write_text(json.dumps(cfg), encoding="utf-8")

    outputs = run_pipeline(config_dir).outputs
    expected = config_dir / "outputs"          # signals.feather 就在 config_dir 下
    assert expected.is_dir()
    assert {p.parent for p in outputs} == {expected}          # 全部平铺，无子目录
    assert not [p for p in expected.iterdir() if p.is_dir()]  # 目录里没有再分层
    assert {p.suffix for p in outputs} == {".png", ".csv", ".feather"}


# 显式 output_dir 仍然优先
def test_explicit_output_dir_wins(config_dir, tmp_path):
    target = tmp_path / "somewhere_else"
    cfg = json.loads((config_dir / "visualizer.json").read_text())
    cfg["output_dir"] = str(target)
    (config_dir / "visualizer.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert {p.parent for p in run_pipeline(config_dir).outputs} == {target}


# 单独用 Visualizer 且两者都没有 → 报错说清楚，而不是悄悄写进 CWD
def test_visualizer_without_any_anchor_is_rejected(config_dir):
    from alpholio import Visualizer
    from alpholio.config_schema import VisualizerConfig

    analysis = run_pipeline(config_dir, render=False).analysis
    with pytest.raises(ContractError, match="output_dir"):
        Visualizer(VisualizerConfig()).run(analysis)
