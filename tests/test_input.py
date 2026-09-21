# Input：列映射、路径变量、日历构建与 auto_stride
from __future__ import annotations

import pytest

from alpholio.config_schema import InputConfig
from alpholio.contracts import ContractError
from alpholio.input import InputProcessor
from alpholio.io import resolve_path


def _cfg(config_dir):
    return InputConfig.from_file(config_dir / "input.json")


def test_column_map_renames_to_contract(config_dir):
    bundle = InputProcessor(_cfg(config_dir)).run()
    assert list(bundle.signals.columns) == ["date", "id", "signal_model", "alpha"]
    assert list(bundle.prices.columns) == ["date", "id", "close", "cap"]
    assert bundle.signals["id"].dtype == object
    assert str(bundle.prices["date"].dtype) == "datetime64[ns]"


def test_reference_carries_frequency(config_dir):
    bundle = InputProcessor(_cfg(config_dir)).run()
    assert set(bundle.references["frequency"]) == {"daily"}


def test_rebalance_freq_subsamples(config_dir):
    bundle = InputProcessor(_cfg(config_dir)).run()
    assert bundle.meta["calendar"]["applied_stride"] == 5
    assert len(bundle.calendar) == 8  # 40 个交易日按 5 抽稀


# 信号日历原生已够稀疏时不再二次抽稀
def test_auto_stride_skips_redundant_subsampling(config_dir):
    cfg = _cfg(config_dir)
    cfg.calendar.auto_stride = True
    cfg.calendar.rebalance_freq = 1
    dense = InputProcessor(cfg).run()
    assert dense.meta["calendar"]["applied_stride"] == 1
    assert dense.meta["calendar"]["native_stride"] == 1


# close 只在价格口径下参与计算，未映射时补 NaN 占位，
# 价格面板照常提供市值关联与交易日历
def test_prices_without_close_mapping(config_dir):
    cfg = _cfg(config_dir)
    cfg.prices.column_map.pop("close")
    bundle = InputProcessor(cfg).run()
    assert list(bundle.prices.columns) == ["date", "id", "close", "cap"]
    assert bundle.prices["close"].isna().all()
    assert bundle.prices["cap"].notna().all()


# 声明了 close 却对不上源列仍要报错，拼写错误不能被当成「未提供」静默吞掉
def test_misspelled_close_is_reported(config_dir):
    cfg = _cfg(config_dir)
    cfg.prices.column_map["close"] = "not_there"
    with pytest.raises(ContractError, match="not_there"):
        InputProcessor(cfg).run()


def test_missing_source_column_is_reported(config_dir):
    cfg = _cfg(config_dir)
    cfg.signals[0].column_map["alpha"] = "not_there"
    with pytest.raises(ContractError, match="not_there"):
        InputProcessor(cfg).run()


def test_path_variable_expansion(tmp_path):
    assert resolve_path("${ROOT}/x.feather", {"ROOT": str(tmp_path)}) == tmp_path / "x.feather"
    with pytest.raises(KeyError):
        resolve_path("${NOPE}/x.feather", {})


def test_empty_signal_list_rejected():
    cfg = InputConfig.from_dict({
        "prices": {"path": "p.feather", "column_map": {"date": "d", "id": "a", "close": "c"}}
    })
    with pytest.raises(ContractError):
        InputProcessor(cfg)
