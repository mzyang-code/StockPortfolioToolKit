# 净值 / 累计对数收益曲线，以及对基准的波动率缩放
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..contracts import (
    BUCKET,
    CUM_LOG_RET,
    DATE,
    EQUITY,
    REFERENCE_BUCKET,
    RET,
    SIGNAL,
    WEIGHT,
)

_KEYS = [SIGNAL, BUCKET, WEIGHT]


# 所有曲线共用的视觉原点：最早一期的前一个工作日
def shared_origin(returns: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(returns[DATE].min()) - pd.tseries.offsets.BDay(1)


# 净值走 (1+r) 累乘，对数曲线走 log1p 累加；每条线前置一个零点
def build_curves(
    returns: pd.DataFrame,
    clip_lower: float = -0.99,
    origin: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    frames = []
    for keys, grp in returns.groupby(_KEYS, sort=False):
        line = grp.dropna(subset=[RET]).sort_values(DATE)
        if line.empty:
            continue
        rets = line[RET].astype(float).clip(lower=clip_lower).to_numpy()
        body = pd.DataFrame({
            DATE: line[DATE].to_numpy(),
            RET: rets,
            EQUITY: np.cumprod(1.0 + rets),
            CUM_LOG_RET: np.log1p(rets).cumsum(),
        })
        start = origin if origin is not None else shared_origin(line)
        head = pd.DataFrame({DATE: [start], RET: [0.0], EQUITY: [1.0], CUM_LOG_RET: [0.0]})
        curve = pd.concat([head, body], ignore_index=True)
        for name, value in zip(_KEYS, keys):
            curve[name] = value
        frames.append(curve)
    if not frames:
        return pd.DataFrame(columns=[DATE, *_KEYS, RET, EQUITY, CUM_LOG_RET])
    out = pd.concat(frames, ignore_index=True)
    return out[[DATE, *_KEYS, RET, EQUITY, CUM_LOG_RET]]


# 全样本单一常数缩放，使各序列波动率对齐基准；基准自身不缩放
def vol_rescale_to_reference(
    returns: pd.DataFrame, reference: str, min_periods: int = 20
) -> pd.DataFrame:
    ref = returns[(returns[SIGNAL] == reference) & (returns[BUCKET] == REFERENCE_BUCKET)]
    if ref.empty:
        ref = returns[returns[SIGNAL] == reference]
    if ref.empty:
        raise ValueError(f"vol_scale.reference='{reference}' 在收益表中不存在")
    targets = {w: _std(g[RET].to_numpy(), min_periods) for w, g in ref.groupby(WEIGHT)}

    def rescale(grp: pd.DataFrame) -> pd.DataFrame:
        if grp[SIGNAL].iloc[0] == reference:
            return grp
        target = targets.get(grp[WEIGHT].iloc[0], np.nan)
        own = _std(grp[RET].to_numpy(), min_periods)
        factor = target / own if np.isfinite(target) and np.isfinite(own) and own > 0 else 1.0
        return grp.assign(**{RET: grp[RET] * factor})

    scaled = [rescale(g) for _, g in returns.groupby(_KEYS, sort=False)]
    return pd.concat(scaled, ignore_index=True)[returns.columns]


def _std(values: np.ndarray, min_periods: int) -> float:
    finite = values[np.isfinite(values)]
    if len(finite) < int(min_periods):
        return float("nan")
    return float(np.std(finite, ddof=1))
