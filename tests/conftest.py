# 合成数据夹具：不依赖任何外部数据，数值可手算校验
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

N_ASSETS = 8
N_DAYS = 40
START = pd.Timestamp("2020-01-01")


@pytest.fixture
def trading_days() -> pd.DatetimeIndex:
    return pd.bdate_range(START, periods=N_DAYS)


# 每只股票一个固定日收益率，close 严格几何增长，前视收益可解析
@pytest.fixture
def prices(trading_days) -> pd.DataFrame:
    rows = []
    for i in range(N_ASSETS):
        daily = 0.001 * (i + 1)
        close = 100.0 * np.cumprod(np.full(N_DAYS, 1.0 + daily))
        rows.append(pd.DataFrame({
            "date": trading_days,
            "id": f"A{i}",
            "close": close,
            "cap": float(10 ** (i + 1)),
        }))
    return pd.concat(rows, ignore_index=True)


# alpha 与资产序号同序，因此分桶结果完全可预测
@pytest.fixture
def signals(trading_days) -> pd.DataFrame:
    rows = []
    for i in range(N_ASSETS):
        rows.append(pd.DataFrame({
            "date": trading_days,
            "id": f"A{i}",
            "signal_model": "SYN",
            "alpha": float(i),
        }))
    return pd.concat(rows, ignore_index=True)


@pytest.fixture
def references(trading_days) -> pd.DataFrame:
    return pd.DataFrame({
        "date": trading_days,
        "name": "BENCH",
        "ret": 0.002,
        "frequency": "daily",
    })


@pytest.fixture
def bundle(signals, prices, references, trading_days):
    from stockportfoliotoolkit.contracts import InputBundle

    return InputBundle(
        signals=signals,
        prices=prices,
        calendar=trading_days[::5],
        references=references,
        meta={},
    )


# 落成磁盘文件 + 一份 input.json，用于端到端读取路径
@pytest.fixture
def config_dir(tmp_path: Path, prices, signals, references) -> Path:
    prices.rename(columns={"date": "d", "id": "sym"}).to_feather(tmp_path / "prices.feather")
    signals[["date", "id", "alpha"]].rename(
        columns={"date": "anchor", "id": "sym"}
    ).to_feather(tmp_path / "signals.feather")
    references[["date", "ret"]].to_csv(tmp_path / "bench.csv", index=False)

    configs = {
        "input.json": {
            "vars": {"ROOT": str(tmp_path)},
            "prices": {
                "path": "${ROOT}/prices.feather",
                "column_map": {"date": "d", "id": "sym", "close": "close", "cap": "cap"},
            },
            "signals": [{
                "name": "SYN",
                "path": "${ROOT}/signals.feather",
                "column_map": {"date": "anchor", "id": "sym", "alpha": "alpha"},
            }],
            "references": [{
                "name": "BENCH",
                "path": "${ROOT}/bench.csv",
                "column_map": {"date": "date", "ret": "ret"},
                "frequency": "daily",
            }],
            "calendar": {"rebalance_freq": 5, "auto_stride": False},
        },
        "engine.json": {
            "n_buckets": 2, "min_names": 4, "forward_return": {"horizon": 5},
            "weights": ["ew", "vw"],
        },
        "analyzer.json": {
            "vol_rescale": {"enabled": True, "reference": "BENCH"},
        },
        "visualizer.json": {
            "output_dir": str(tmp_path / "out"),
            "charts": [{"name": "curve", "buckets": ["H-L", "REF"], "weights": ["EW"]}],
            "tables": [{"name": "metrics", "type": "summary"}],
        },
    }
    for filename, payload in configs.items():
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path
