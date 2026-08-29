# 截面分桶与组合收益：严格只用简单收益加权
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from ..config import EngineConfig
from ..contracts import (
    ALPHA,
    BUCKET,
    DATE,
    FWD_RET,
    N_NAMES,
    RET,
    SIGNAL,
    WEIGHT,
    ContractError,
)
from .weighting import Weighter


# 每个 (调仓日, 信号) 内按 alpha 等频分桶；名字不足或分位退化则整日作废
def assign_buckets(panel: pd.DataFrame, n_buckets: int, min_names: int) -> pd.DataFrame:
    n_buckets = int(n_buckets)
    if n_buckets < 2:
        raise ContractError(f"engine.n_buckets 必须 >= 2，得到 {n_buckets}")

    def cut(series: pd.Series) -> pd.Series:
        if series.notna().sum() < int(min_names):
            return pd.Series(np.nan, index=series.index)
        try:
            return pd.qcut(series, n_buckets, labels=False, duplicates="drop")
        except ValueError:
            return pd.Series(np.nan, index=series.index)

    out = panel.copy()
    out[BUCKET] = out.groupby([DATE, SIGNAL], sort=False)[ALPHA].transform(cut)
    out = out.dropna(subset=[BUCKET])
    out[BUCKET] = out[BUCKET].astype(int).astype(str)
    return out


# 逐 (日, 信号, 桶) 调用每个权重器，组合收益 = Σ wᵢ·retᵢ
def bucket_returns(members: pd.DataFrame, weighters: Sequence[Weighter]) -> pd.DataFrame:
    rows: List[Dict] = []
    for (date, signal, bucket), frame in members.groupby([DATE, SIGNAL, BUCKET], sort=False):
        realised = frame[FWD_RET].to_numpy(dtype=np.float64)
        for weighter in weighters:
            w = weighter.weights(frame)
            rows.append({
                DATE: date,
                SIGNAL: signal,
                BUCKET: bucket,
                WEIGHT: weighter.label,
                RET: np.nan if w is None else float(np.dot(w, realised)),
                N_NAMES: len(frame),
            })
    return pd.DataFrame(rows, columns=list((DATE, SIGNAL, BUCKET, WEIGHT, RET, N_NAMES)))


# 多空组合 = 高桶 − 低桶（reverse 时反向），按 (日, 信号, 权重) 对齐
def long_short_returns(returns: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    spec = cfg.long_short
    long_b, short_b = long_short_buckets(cfg)
    index = [DATE, SIGNAL, WEIGHT]
    wide = returns.pivot_table(index=index, columns=BUCKET, values=RET, aggfunc="first")
    if long_b not in wide.columns or short_b not in wide.columns:
        return returns.iloc[0:0].copy()
    names = returns.pivot_table(index=index, columns=BUCKET, values=N_NAMES, aggfunc="first")

    out = (wide[long_b] - wide[short_b]).rename(RET).reset_index()
    out[BUCKET] = spec.label
    out[N_NAMES] = (
        names.get(long_b, 0).fillna(0) + names.get(short_b, 0).fillna(0)
    ).astype(int).to_numpy()
    return out[[DATE, SIGNAL, BUCKET, WEIGHT, RET, N_NAMES]]


# 多头端与空头端的桶标签
def long_short_buckets(cfg: EngineConfig) -> Tuple[str, str]:
    top, bottom = str(int(cfg.n_buckets) - 1), "0"
    return (bottom, top) if cfg.long_short.reverse else (top, bottom)
