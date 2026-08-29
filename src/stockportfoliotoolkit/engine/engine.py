# ② Portfolio Engine：面板 → 分桶 → 组合收益长表
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from ..config import EngineConfig
from ..contracts import (
    BUCKET,
    DATE,
    FREQ_DAILY,
    FREQUENCY,
    MEMBER_COLUMNS,
    N_NAMES,
    NAME,
    REFERENCE_BUCKET,
    RET,
    RETURN_COLUMNS,
    SIGNAL,
    WEIGHT,
    ContractError,
    EngineResult,
    InputBundle,
)
from .alignment import build_panel
from .cross_section import (
    assign_buckets,
    bucket_returns,
    long_short_buckets,
    long_short_returns,
)
from .weighting import build_weighter


class PortfolioEngine:
    def __init__(self, cfg: EngineConfig) -> None:
        if not cfg.weights:
            raise ContractError("engine.weights 为空，至少需要一个权重方案")
        self.cfg = cfg
        self.weighters = [
            build_weighter(name, cfg.weight_options.get(name)) for name in cfg.weights
        ]
        labels = [w.label for w in self.weighters]
        if len(set(labels)) != len(labels):
            raise ContractError(f"权重方案输出标签重复: {labels}")

    # 唯一出口
    def run(self, bundle: InputBundle) -> EngineResult:
        cfg = self.cfg
        aligned = build_panel(bundle, cfg)
        members = assign_buckets(aligned, cfg.n_buckets, cfg.min_names)
        if members.empty:
            raise ContractError(
                f"没有任何调仓日通过分桶（min_names={cfg.min_names}，"
                f"n_buckets={cfg.n_buckets}），请放宽门槛或检查数据覆盖"
            )
        parts: List[pd.DataFrame] = [bucket_returns(members, self.weighters)]
        if cfg.long_short.enabled:
            parts.append(long_short_returns(parts[0], cfg))
        if cfg.include_references and bundle.references is not None:
            parts.append(self._reference_returns(bundle))

        returns = pd.concat([p for p in parts if not p.empty], ignore_index=True)
        returns = returns[list(RETURN_COLUMNS)].sort_values([SIGNAL, BUCKET, WEIGHT, DATE])
        return EngineResult(
            returns=returns.reset_index(drop=True),
            members=members[list(MEMBER_COLUMNS)].reset_index(drop=True),
            aligned=aligned,
            meta=self._describe(returns, members),
        )

    # 外部基准按持有期折算后，对每个权重方案各复制一行，方便下游统一过滤
    def _reference_returns(self, bundle: InputBundle) -> pd.DataFrame:
        cfg = self.cfg
        frames: List[pd.DataFrame] = []
        for name, grp in bundle.references.groupby(NAME, sort=True):
            frequency = str(grp[FREQUENCY].iloc[0]).lower()
            if frequency == FREQ_DAILY:
                series = _compound(grp, bundle.calendar, cfg.holding_days, cfg.reference_lag)
            else:
                series = grp[grp[DATE].isin(bundle.calendar)][[DATE, RET]]
            if series.empty:
                continue
            for weighter in self.weighters:
                frame = series.copy()
                frame[SIGNAL] = name
                frame[BUCKET] = REFERENCE_BUCKET
                frame[WEIGHT] = weighter.label
                frame[N_NAMES] = 0
                frames.append(frame[list(RETURN_COLUMNS)])
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=list(RETURN_COLUMNS)
        )

    def _describe(self, returns: pd.DataFrame, members: pd.DataFrame) -> Dict:
        spec = self.cfg.long_short
        long_bucket, short_bucket = long_short_buckets(self.cfg)
        return {
            "holding_days": int(self.cfg.holding_days),
            "n_buckets": int(self.cfg.n_buckets),
            "weights": [w.label for w in self.weighters],
            "long_short_label": spec.label if spec.enabled else None,
            "long_bucket": long_bucket if spec.enabled else None,
            "short_bucket": short_bucket if spec.enabled else None,
            "reference_bucket": REFERENCE_BUCKET,
            "periods": int(members[DATE].nunique()),
            "signals": sorted(returns[SIGNAL].unique().tolist()),
            "rows": int(len(returns)),
        }


# 日频基准在 [锚点+lag, 锚点+lag+持有期) 上复利成持有期收益
def _compound(
    reference: pd.DataFrame, calendar: pd.DatetimeIndex, holding_days: int, lag: int
) -> pd.DataFrame:
    dates = reference[DATE].to_numpy()
    rets = reference[RET].to_numpy(dtype=np.float64)
    h, lag = int(holding_days), int(lag)
    rows = []
    for anchor in calendar:
        pos = int(np.searchsorted(dates, anchor.to_datetime64(), side="left"))
        if pos >= len(dates) or dates[pos] != anchor.to_datetime64():
            continue
        window = rets[pos + lag: pos + lag + h]
        if len(window) < h:
            continue
        rows.append({DATE: anchor, RET: float(np.prod(1.0 + window) - 1.0)})
    return pd.DataFrame(rows, columns=[DATE, RET])
