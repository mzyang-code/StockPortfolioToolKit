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


# ============================ 月频夹具 ============================
# 两年整、每月一期。月末口径可解析：第 i 只股票每月固定涨 1%×(i+1)，
# 因此 h 个自然月的前视收益恰为 (1 + 0.01(i+1))^h − 1。

N_MONTHS = 24
MONTHLY_FIRST = "2019-01-01"
MONTHLY_LAST = "2020-12-31"
# 月内非月末交易日的偏离幅度。取数若没落在月末，价格与市值都会明显对不上，
# 「按自然月对齐」因此是可证伪的，而不是恰好相等。
INTRA_MONTH_CLOSE_LIFT = 1.05
INTRA_MONTH_CAP_FACTOR = 10.0


def monthly_growth(i: int) -> float:
    return 1.0 + 0.01 * (i + 1)


@pytest.fixture
def business_days() -> pd.DatetimeIndex:
    return pd.bdate_range(MONTHLY_FIRST, MONTHLY_LAST)


@pytest.fixture
def month_ends(business_days) -> pd.DatetimeIndex:
    grouped = pd.Series(business_days).groupby(business_days.to_period("M")).max()
    return pd.DatetimeIndex(grouped.to_numpy())


# 每月第三个交易日：调仓锚点落在月内、而非月末的形态
@pytest.fixture
def month_thirds(business_days) -> pd.DatetimeIndex:
    grouped = pd.Series(business_days).groupby(business_days.to_period("M")).nth(2)
    return pd.DatetimeIndex(grouped.to_numpy())


# 纯月频面板：一行 = 一个资产一个自然月
@pytest.fixture
def monthly_prices(month_ends) -> pd.DataFrame:
    steps = np.arange(len(month_ends))
    return pd.concat([
        pd.DataFrame({
            "date": month_ends,
            "id": f"A{i}",
            "close": 100.0 * monthly_growth(i) ** steps,
            "cap": float(10 ** (i + 1)),
        })
        for i in range(N_ASSETS)
    ], ignore_index=True)


# 日频面板，月末的 close 与 cap 与 monthly_prices 逐值相同，月内其余交易日刻意错开
@pytest.fixture
def intramonth_prices(business_days, month_ends) -> pd.DataFrame:
    order = {period: k for k, period in enumerate(sorted(set(business_days.to_period("M"))))}
    month_of_day = np.array([order[p] for p in business_days.to_period("M")])
    at_month_end = business_days.isin(month_ends)
    frames = []
    for i in range(N_ASSETS):
        close = 100.0 * monthly_growth(i) ** month_of_day
        cap = float(10 ** (i + 1))
        frames.append(pd.DataFrame({
            "date": business_days,
            "id": f"A{i}",
            "close": np.where(at_month_end, close, close * INTRA_MONTH_CLOSE_LIFT),
            "cap": np.where(at_month_end, cap, cap * INTRA_MONTH_CAP_FACTOR),
        }))
    return pd.concat(frames, ignore_index=True)


# alpha 与资产序号同序，逐期不变：分桶与多空腿因此完全可预测
def _alpha_panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.concat([
        pd.DataFrame({
            "date": dates,
            "id": f"A{i}",
            "signal_model": "SYN",
            "alpha": float(i),
        })
        for i in range(N_ASSETS)
    ], ignore_index=True)


@pytest.fixture
def monthly_signals(month_ends) -> pd.DataFrame:
    return _alpha_panel(month_ends)


# 信号每个交易日都有：月度口径须自行把日历落到月末
@pytest.fixture
def daily_signals_over_months(business_days) -> pd.DataFrame:
    return _alpha_panel(business_days)


# 信号只在月内第三个交易日落盘：锚点与价格面板的月末不是同一天
@pytest.fixture
def midmonth_signals(month_thirds) -> pd.DataFrame:
    return _alpha_panel(month_thirds)


@pytest.fixture
def daily_reference(business_days) -> pd.DataFrame:
    return pd.DataFrame({
        "date": business_days,
        "name": "BENCH",
        "ret": 0.002,
        "frequency": "daily",
    })


@pytest.fixture
def bundle(signals, prices, references, trading_days):
    from alpholio.contracts import InputBundle

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
