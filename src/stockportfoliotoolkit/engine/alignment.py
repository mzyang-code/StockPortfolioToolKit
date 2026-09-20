# alpha × 前视收益 × 市值 的对齐，产出 Engine 的输入面板
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ..config_schema import EngineConfig
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


class DegeneratePriceWarning(UserWarning):
    """close 逐资产恒定：由它推出的前视收益恒为 0，通常是占位列被当成了真实价格"""


class IgnoredForwardReturnWarning(UserWarning):
    """信号自带 fwd_ret 但配置取价格口径：自带列被丢弃，以 close 推算为准"""


# 逐资产 close[t+h]/close[t]-1，纯价格口径，与 alpha 的预测期解耦
def forward_returns(prices: pd.DataFrame, holding_days: int) -> pd.DataFrame:
    h = int(holding_days)
    if h < 1:
        raise ContractError(f"engine.holding_days 必须 >= 1，得到 {h}")
    panel = prices.sort_values([ASSET, DATE])
    ahead = panel.groupby(ASSET, sort=False)[CLOSE].shift(-h)
    out = panel[[DATE, ASSET]].copy()
    out[FWD_RET] = (ahead / panel[CLOSE] - 1.0).to_numpy()
    _warn_on_degenerate_prices(out[FWD_RET])
    return out


# 全样本每期收益恰好为 0 意味着 close 在每个资产内都没动过，真实行情不会如此。
# 停牌等局部零收益不触发；全 NaN 也不触发——那是 close 整列缺失，由 _require_close 截断。
def _warn_on_degenerate_prices(fwd_ret: pd.Series) -> None:
    usable = fwd_ret.dropna()
    if usable.empty or not (usable == 0.0).all():
        return
    warnings.warn(
        "价格面板的 close 在每个资产内均无变化，由它推出的前视收益恒为 0，"
        "据此得到的组合收益、净值与所有指标都没有意义。"
        "若 close 是为通过校验而填的占位列，应改用 "
        "engine.forward_return.source='signals'，并在信号的 column_map 中映射 fwd_ret 列。",
        DegeneratePriceWarning,
        stacklevel=3,
    )


# close 未映射时整列为 NaN，前视收益会整体算空，下游只会报「没有任何调仓日通过分桶」，
# 指不回真正的原因。在此处截断，把矛盾直接摆回配置本身。
def _require_close(prices: pd.DataFrame) -> None:
    if prices[CLOSE].notna().any():
        return
    raise ContractError(
        "engine.forward_return.source='prices' 需要价格面板提供 close，"
        "但 input.prices.column_map 未映射该列（当前 close 整列为空）。"
        "补上 close 映射，或改用 source='signals' 并映射信号文件自带的 fwd_ret 列。"
    )


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
        _require_close(bundle.prices)
        # 信号自带的 fwd_ret 与价格口径同名，留着会在 merge 后裂成 fwd_ret_x / fwd_ret_y，
        # 两边都不叫 fwd_ret。配置既已指定价格口径，就以价格为准丢弃自带列。
        if FWD_RET in signals.columns:
            warnings.warn(
                "信号的 column_map 映射了 fwd_ret，但 engine.forward_return.source='prices'："
                "自带的前视收益已忽略，实际取 close 推算的价格口径。"
                "要改用自带列请把 source 设为 'signals'。",
                IgnoredForwardReturnWarning,
                stacklevel=3,
            )
            signals = signals.drop(columns=[FWD_RET])
        # 测量期长度取 forward_return.horizon，与 holding_days 的年化口径解耦
        fwd = forward_returns(bundle.prices, cfg.forward_return.horizon)
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
