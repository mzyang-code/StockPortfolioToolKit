# 组合层指标：可注册、只吃一维简单收益序列
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..registry import Registry

METRICS: Registry = Registry("metric")


@dataclass(frozen=True)
class MetricContext:
    periods_per_year: float
    risk_free_rate: float = 0.0


class Metric(ABC):
    name: str = ""

    @abstractmethod
    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        ...


@METRICS.register()
class AnnualizedReturn(Metric):
    name = "ann_ret"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        return float(rets.mean() * ctx.periods_per_year)


# 净值按简单收益累乘，再折回每年一期的复合增长率。与 ann_ret 是两套口径：
# ann_ret 把单期收益线性放大 P 倍，cagr 则让它们逐期滚动复利。月频面板上后者通常明显
# 更高——复利的凸性 (1+m)^P − 1 > m·P 压过了波动拖累。净值跌破 0 时复合增长率无定义。
@METRICS.register()
class CompoundAnnualGrowthRate(Metric):
    name = "cagr"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        if len(rets) == 0:
            return float("nan")
        equity = float(np.cumprod(1.0 + rets)[-1])
        if equity <= 0.0:
            return float("nan")
        return float(equity ** (ctx.periods_per_year / len(rets)) - 1.0)


@METRICS.register()
class AnnualizedVolatility(Metric):
    name = "ann_vol"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        if len(rets) < 2:
            return float("nan")
        return float(rets.std(ddof=1) * np.sqrt(ctx.periods_per_year))


@METRICS.register()
class Sharpe(Metric):
    name = "sharpe"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        vol = AnnualizedVolatility().compute(rets, ctx)
        if not np.isfinite(vol) or vol <= 0:
            return float("nan")
        return float((AnnualizedReturn().compute(rets, ctx) - ctx.risk_free_rate) / vol)


# 净值按简单收益复利，回撤取全程最低点
@METRICS.register()
class MaxDrawdown(Metric):
    name = "max_drawdown"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        equity = np.cumprod(1.0 + rets)
        return float((equity / np.maximum.accumulate(equity) - 1.0).min())


@METRICS.register()
class TotalEquity(Metric):
    name = "total_equity"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        return float(np.cumprod(1.0 + rets)[-1])


def build_metric(name: str) -> Metric:
    return METRICS.get(name)()
