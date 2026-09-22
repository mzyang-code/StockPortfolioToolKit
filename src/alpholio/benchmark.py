# S&P 500 日频指数的买入持有曲线，按给定日期轴取样。
#
# 该模块不参与渲染链路：Visualizer 不再自动叠加这条曲线，配置中也没有对应开关。
# 基准改由 input.references 声明，使用者自备数据。此处代码与 data/ 下的序列一并
# 保留，供仓库内的示例与 notebook 复现历史结果时调用。
#
# data/ 下的序列受数据使用权限制，不随 sdist 与 wheel 分发（见 pyproject.toml），
# 因此这些函数只在仓库内（或源码安装）可用，在 wheel 安装的环境中会抛
# FileNotFoundError。
from __future__ import annotations

from functools import lru_cache
from types import MappingProxyType
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from .contracts import CUM_LOG_RET, DATE, EQUITY

# 数据来源：CRSP S&P 500 Universe 组合日频总收益（含股息），1992-01-02 ~ 2025-12-31，8561 个交易日。
#   ew_ret ← CRSP Equal-Weighted Portfolios of the S&P 500 Universe  (DlyTotRet)
#   vw_ret ← CRSP Value-Weighted Portfolios of the S&P 500 Universe  (DlyTotRet)
# 原始文件保留在仓库 cache/sp500_daily_{ew,vw}.csv.gz 以便复核。
DATA_FILE = "sp500_daily.csv.gz"
DATA_DIR = "data"

# 加权方案 → 基准列。EW 组合对 EW 指数、VW 组合对 VW 指数，这样比较才是同口径的。
# 未登记的方案退回市值加权——那才是通常说的「S&P 500」。
_COLUMN_BY_WEIGHT = {"EW": "ew_ret", "VW": "vw_ret"}
_DEFAULT_COLUMN = "vw_ret"
_LABEL_BY_COLUMN = {"ew_ret": "S&P 500 EW", "vw_ret": "S&P 500 VW"}

# 示例里画这条曲线时用的样式。MappingProxyType 让误改在写入处就抛 TypeError，
# 而不是静默生效。Visualizer 不读取该常量。
BENCHMARK_STYLE: Mapping[str, object] = MappingProxyType({
    "color": "#000000",
    "linestyle": "-",
    "linewidth": 1.9,
    "zorder": 10,  # 压在所有组合曲线之上，避免被分位线盖住
})


def _column_for(weight: Optional[str]) -> str:
    return _COLUMN_BY_WEIGHT.get(str(weight).upper(), _DEFAULT_COLUMN)


def benchmark_label(weight: Optional[str] = None) -> str:
    """图例文案，跟随该图的加权方案。"""
    return _LABEL_BY_COLUMN[_column_for(weight)]


@lru_cache(maxsize=1)
def load_sp500_daily() -> pd.DataFrame:
    """读取 data/ 下的 S&P 500 日频收益，返回 [date, ew_ret, vw_ret]（升序、无重复）。

    该序列不随 wheel 分发，仅在仓库内或源码安装时存在。缺失时抛 FileNotFoundError。
    """
    from importlib.resources import files

    # 逐级 joinpath：多参数形式要 Python 3.11+，而本包声明支持 3.10
    resource = files(__package__).joinpath(DATA_DIR).joinpath(DATA_FILE)
    try:
        handle = resource.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise FileNotFoundError(
            f"未找到 {DATA_DIR}/{DATA_FILE}。该序列受数据使用权限制，不随安装包分发，"
            "只在仓库内或源码安装时可用。基准请改用 input.references 自备数据声明。"
        ) from exc
    with handle as fh:
        frame = pd.read_csv(fh, compression="gzip")
    frame[DATE] = pd.to_datetime(frame[DATE])
    for column in _COLUMN_BY_WEIGHT.values():
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(np.float64)
    frame = frame.dropna().sort_values(DATE).reset_index(drop=True)
    return frame[[DATE, *sorted(_COLUMN_BY_WEIGHT.values())]]


# 从 origin 起买入持有，按 dates 取样；组合怎么调仓与基准无关，
# 因此这里不涉及 holding_days / rebalance_freq，不会被重叠持有期污染。
def benchmark_curve(dates, weight: Optional[str] = None) -> pd.DataFrame:
    """给定图表日期轴与加权方案，返回同轴的 [date, equity, cum_log_ret] 基准曲线。

    origin 取 dates 的最小值，其净值定为 1.0。取样用 asof（每个日期取 <= 它的
    最后一个交易日）。落在数据覆盖区间之外的日期记 NaN，不外推。
    """
    axis = pd.DatetimeIndex(pd.unique(pd.DatetimeIndex(dates))).sort_values()
    empty = pd.DataFrame(columns=[DATE, EQUITY, CUM_LOG_RET])
    if len(axis) == 0:
        return empty

    daily = load_sp500_daily()
    days = daily[DATE].to_numpy()
    # C[i] = 截至第 i 个交易日（含）的累计净值；前置 1.0 表示「首个交易日之前」
    growth = np.concatenate([[1.0], np.cumprod(1.0 + daily[_column_for(weight)].to_numpy())])

    pos = np.searchsorted(days, axis.to_numpy(), side="right")
    level = growth[pos]

    covered = (pos > 0) & (axis.to_numpy() <= days[-1])
    if not covered[0] or level[0] <= 0:
        return empty  # 起点不在数据覆盖区间内，整条曲线无从归一

    equity = np.where(covered, level / level[0], np.nan)
    return pd.DataFrame({
        DATE: axis,
        EQUITY: equity,
        CUM_LOG_RET: np.log(equity, where=np.isfinite(equity), out=np.full_like(equity, np.nan)),
    })
