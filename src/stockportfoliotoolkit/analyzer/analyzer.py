# ③ Analyzer：组合收益 → 指标汇总 + 曲线 + 诊断
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from ..config import AnalyzerConfig
from ..contracts import (
    BUCKET,
    DATE,
    IC,
    N_NAMES,
    RET,
    SIGNAL,
    TURNOVER,
    WEIGHT,
    AnalysisResult,
    ContractError,
    EngineResult,
    sort_by_bucket,
)
from .curves import build_curves, shared_origin, vol_rescale_to_reference
from .diagnostics import compute_ic, compute_turnover
from .metrics import MetricContext, build_metric


class Analyzer:
    def __init__(self, cfg: AnalyzerConfig) -> None:
        self.cfg = cfg
        self.metrics = [build_metric(name) for name in cfg.metrics]

    # 唯一出口
    def run(self, result: EngineResult) -> AnalysisResult:
        cfg = self.cfg
        ppy = self._periods_per_year(result.meta)
        ctx = MetricContext(periods_per_year=ppy, risk_free_rate=cfg.risk_free_rate)

        turnover = (
            compute_turnover(
                result.members,
                long_short_label=result.meta.get("long_short_label"),
                long_bucket=result.meta.get("long_bucket"),
                short_bucket=result.meta.get("short_bucket"),
            )
            if cfg.diagnostics.turnover
            else _empty(SIGNAL, BUCKET, DATE, TURNOVER)
        )
        ic = (
            compute_ic(result.aligned, cfg.diagnostics.ic_min_names)
            if cfg.diagnostics.ic
            else _empty(SIGNAL, DATE, IC, N_NAMES)
        )

        returns = self._rescale(result.returns)
        origin = shared_origin(returns) if cfg.curves.shared_origin else None

        return AnalysisResult(
            summary=self._summarize(returns, ctx, turnover, ic),
            curves=build_curves(returns, cfg.curves.clip_lower, origin),
            turnover=turnover,
            ic=ic,
            meta={
                "periods_per_year": ppy,
                "metrics": [m.name for m in self.metrics],
                "vol_rescaled": bool(cfg.vol_rescale.enabled),
                "vol_rescale_reference": cfg.vol_rescale.reference if cfg.vol_rescale.enabled else None,
                **{k: result.meta[k] for k in ("holding_days", "n_buckets") if k in result.meta},
            },
        )

    # 开关打开时整体替换为缩放后的收益，不再并列输出两套口径
    def _rescale(self, returns: pd.DataFrame) -> pd.DataFrame:
        spec = self.cfg.vol_rescale
        if not spec.enabled:
            return returns
        if not spec.reference:
            raise ContractError(
                "analyzer.vol_rescale.enabled=true 时必须指定 reference（缩放到哪个基准）"
            )
        return vol_rescale_to_reference(returns, spec.reference, spec.min_periods)

    # 年化因子：显式配置优先，否则由交易日数 / 持有期推导
    def _periods_per_year(self, engine_meta: Dict) -> float:
        if self.cfg.periods_per_year:
            return float(self.cfg.periods_per_year)
        holding = int(engine_meta.get("holding_days", 1))
        return float(self.cfg.trading_days_per_year) / max(holding, 1)

    def _summarize(
        self, returns: pd.DataFrame, ctx: MetricContext, turnover: pd.DataFrame, ic: pd.DataFrame
    ) -> pd.DataFrame:
        turnover_mean = _mean_by(turnover, [SIGNAL, BUCKET], TURNOVER)
        ic_mean = _mean_by(ic, [SIGNAL], IC)
        rows: List[Dict] = []
        for (signal, bucket, weight), grp in returns.groupby(
            [SIGNAL, BUCKET, WEIGHT], sort=True
        ):
            series = grp[RET].dropna().to_numpy(dtype=np.float64)
            if len(series) == 0:
                continue
            row = {
                SIGNAL: signal, BUCKET: bucket, WEIGHT: weight,
                "n_periods": int(len(series)),
            }
            row.update({m.name: m.compute(series, ctx) for m in self.metrics})
            row[TURNOVER] = turnover_mean.get((signal, bucket), np.nan)
            row["ic_mean"] = ic_mean.get(signal, np.nan)
            rows.append(row)
        return sort_by_bucket(pd.DataFrame(rows), [SIGNAL, WEIGHT])


def _empty(*columns: str) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _mean_by(frame: pd.DataFrame, keys: List[str], column: str) -> Dict:
    if frame.empty or column not in frame.columns:
        return {}
    grouped = frame.groupby(keys[0] if len(keys) == 1 else keys, sort=False)[column].mean()
    return grouped.to_dict()
