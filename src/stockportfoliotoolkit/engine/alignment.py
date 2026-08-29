# alpha × 前视收益 × 市值 的对齐，产出 Engine 的输入面板
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import EngineConfig
from ..contracts import (
    ALIGNED_COLUMNS,
    ALPHA,
    ASSET,
    CAP,
    CLOSE,
    DATE,
    FWD_RET,
    ContractError,
    InputBundle,
)


# 逐资产 close[t+h]/close[t]-1，纯价格口径，与 alpha 的预测期解耦
def forward_returns(prices: pd.DataFrame, holding_days: int) -> pd.DataFrame:
    h = int(holding_days)
    if h < 1:
        raise ContractError(f"engine.holding_days 必须 >= 1，得到 {h}")
    panel = prices.sort_values([ASSET, DATE])
    ahead = panel.groupby(ASSET, sort=False)[CLOSE].shift(-h)
    out = panel[[DATE, ASSET]].copy()
    out[FWD_RET] = (ahead / panel[CLOSE] - 1.0).to_numpy()
    return out


# 按 (调仓日, 资产) 精确取当日市值；取不到即 NaN，该成分自动退出市值加权
def attach_caps(panel: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    return panel.merge(prices[[DATE, ASSET, CAP]], on=[DATE, ASSET], how="left")


# 组装 [date, asset, signal, alpha, fwd_ret, cap]，仅保留调仓日
def build_panel(bundle: InputBundle, cfg: EngineConfig) -> pd.DataFrame:
    source = str(cfg.forward_return.source).lower()
    signals = bundle.signals[bundle.signals[DATE].isin(bundle.calendar)].copy()
    if signals.empty:
        raise ContractError("信号在调仓日历上没有任何记录，检查 calendar 与信号日期是否对齐")

    if source == "prices":
        fwd = forward_returns(bundle.prices, cfg.holding_days)
        panel = signals.merge(fwd, on=[DATE, ASSET], how="left")
    elif source == "signals":
        if FWD_RET not in signals.columns:
            raise ContractError(
                "forward_return.source='signals' 需要信号 column_map 中映射 fwd_ret 列"
            )
        panel = signals
    else:
        raise ContractError(f"未知的 forward_return.source: {cfg.forward_return.source}")

    clip = cfg.forward_return.clip_lower
    if clip is not None:
        panel[FWD_RET] = panel[FWD_RET].clip(lower=float(clip))

    panel = attach_caps(panel, bundle.prices)
    panel = panel.dropna(subset=[ALPHA, FWD_RET])
    return panel[list(ALIGNED_COLUMNS)].reset_index(drop=True)
