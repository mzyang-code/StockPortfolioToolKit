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


@METRICS.register()
class HitRate(Metric):
    name = "hit_rate"

    def compute(self, rets: np.ndarray, ctx: MetricContext) -> float:
        return float((rets > 0).mean())


def build_metric(name: str) -> Metric:
    return METRICS.get(name)()
