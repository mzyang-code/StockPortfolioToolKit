# 换手率与信息系数：只依赖 Engine 交出的成分表与对齐面板
from __future__ import annotations

from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

from ..contracts import (
    ALPHA,
    ASSET,
    BUCKET,
    DATE,
    FWD_RET,
    IC,
    N_NAMES,
    SIGNAL,
    TURNOVER,
)


# 相邻两期成分的 Jaccard 距离；多空桶取多头与空头的并集
def compute_turnover(
    members: pd.DataFrame,
    long_short_label: Optional[str] = None,
    long_bucket: Optional[str] = None,
    short_bucket: Optional[str] = None,
) -> pd.DataFrame:
    rows: List[Dict] = []
    for signal, per_signal in members.groupby(SIGNAL, sort=True):
        previous: Dict[str, Set[str]] = {}
        for date, frame in per_signal.groupby(DATE, sort=True):
            current = {
                str(bucket): set(grp[ASSET])
                for bucket, grp in frame.groupby(BUCKET, sort=False)
            }
            if long_short_label and long_bucket in current and short_bucket in current:
                current[long_short_label] = current[long_bucket] | current[short_bucket]
            for bucket, names in current.items():
                prior = previous.get(bucket)
                union = (names | prior) if prior is not None else None
                rows.append({
                    SIGNAL: signal,
                    BUCKET: bucket,
                    DATE: date,
                    TURNOVER: 1.0 - len(names & prior) / len(union) if union else np.nan,
                })
            previous = current
    return pd.DataFrame(rows, columns=[SIGNAL, BUCKET, DATE, TURNOVER])


# 每期截面 alpha 与实现收益的 Spearman 相关（秩的 Pearson）
def compute_ic(aligned: pd.DataFrame, min_names: int = 20) -> pd.DataFrame:
    panel = aligned.dropna(subset=[ALPHA, FWD_RET]).copy()
    if panel.empty:
        return pd.DataFrame(columns=[SIGNAL, DATE, IC, N_NAMES])
    keys = [SIGNAL, DATE]
    x = panel.groupby(keys, sort=False)[ALPHA].rank()
    y = panel.groupby(keys, sort=False)[FWD_RET].rank()
    # 秩的 Pearson 相关，用各阶和一次聚合出来，避免逐组 apply
    stats = panel.assign(_x=x, _y=y, _xx=x * x, _yy=y * y, _xy=x * y).groupby(keys, sort=True).agg(
        n=("_x", "size"), sx=("_x", "sum"), sy=("_y", "sum"),
        sxx=("_xx", "sum"), syy=("_yy", "sum"), sxy=("_xy", "sum"),
    )
    cov = stats["sxy"] - stats["sx"] * stats["sy"] / stats["n"]
    var_x = stats["sxx"] - stats["sx"] ** 2 / stats["n"]
    var_y = stats["syy"] - stats["sy"] ** 2 / stats["n"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = cov / np.sqrt(var_x * var_y)
    ic = ic.where(stats["n"] >= int(min_names))
    out = pd.DataFrame({IC: ic, N_NAMES: stats["n"]}).reset_index()
    return out[[SIGNAL, DATE, IC, N_NAMES]]
