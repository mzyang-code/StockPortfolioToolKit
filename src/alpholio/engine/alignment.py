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
from ..frequency import DAILY, MONTH_COLUMN as _MONTH, last_per_month, month_key, resolve


class DegeneratePriceWarning(UserWarning):
    """close 逐资产恒定：由它推出的前视收益恒为 0，通常是占位列被当成了真实价格"""


class IgnoredForwardReturnWarning(UserWarning):
    """信号自带 fwd_ret 但配置取价格口径：自带列被丢弃，以 close 推算为准"""


# 逐资产 close[t+h]/close[t]-1，纯价格口径，与 alpha 的预测期解耦。
# h 的单位随频率：日频数一行一期，月频数一个自然月一期（产出表因此每资产每月一行）。
def forward_returns(
    prices: pd.DataFrame, holding_days: int, frequency=DAILY
) -> pd.DataFrame:
    h = int(holding_days)
    if h < 1:
        raise ContractError(f"engine.holding_days 必须 >= 1，得到 {h}")
    if resolve(frequency).is_monthly:
        out = _monthly_forward_returns(prices, h)
    else:
        panel = prices.sort_values([ASSET, DATE])
        ahead = panel.groupby(ASSET, sort=False)[CLOSE].shift(-h)
        out = panel[[DATE, ASSET]].copy()
        out[FWD_RET] = (ahead / panel[CLOSE] - 1.0).to_numpy()
    _warn_on_degenerate_prices(out[FWD_RET])
    return out


# 月频前视收益：先把每个资产压成「每个自然月一个月末收盘价」，再按自然月序号自连接，
# 把 t+h 月的收盘价挂到 t 月上。
#
# 按自然月序号连接而不是在月末序列上 shift(-h)：某资产中途缺月时，shift 会够到「h 个
# 可用月之后」，把缺口悄悄跨过去；按序号连接则连不上，该期留 NaN 并在下游被丢弃。
def _monthly_forward_returns(prices: pd.DataFrame, h: int) -> pd.DataFrame:
    bars = last_per_month(prices[[DATE, ASSET, CLOSE]], [ASSET], DATE, _MONTH)
    ahead = bars[[ASSET, _MONTH, CLOSE]].rename(columns={CLOSE: "_close_ahead"})
    ahead[_MONTH] = ahead[_MONTH] - h
    merged = bars.merge(ahead, on=[ASSET, _MONTH], how="left")
    out = merged[[DATE, ASSET]].copy()
    out[FWD_RET] = (merged["_close_ahead"] / merged[CLOSE] - 1.0).to_numpy()
    return out.reset_index(drop=True)


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


# 按 (调仓日, 资产) 精确取当日市值；取不到即 NaN，该成分自动退出市值加权。
# 月频取该资产当月最后一个可用市值——一个月只认一个权重基准，月内哪天调仓不影响取数。
def attach_caps(panel: pd.DataFrame, prices: pd.DataFrame, frequency=DAILY) -> pd.DataFrame:
    if not resolve(frequency).is_monthly:
        return panel.merge(prices[[DATE, ASSET, CAP]], on=[DATE, ASSET], how="left")
    caps = last_per_month(prices[[DATE, ASSET, CAP]], [ASSET], DATE, _MONTH)
    out = panel.copy()
    out[_MONTH] = month_key(out[DATE])
    out = out.merge(caps[[ASSET, _MONTH, CAP]], on=[ASSET, _MONTH], how="left")
    return out.drop(columns=[_MONTH])


# 组装 [date, asset, signal, alpha, fwd_ret, cap]，仅保留调仓日
def build_panel(bundle: InputBundle, cfg: EngineConfig) -> pd.DataFrame:
    frequency = resolve(bundle.frequency)
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
        fwd = forward_returns(bundle.prices, cfg.forward_return.horizon, frequency)
        panel = _merge_forward(signals, fwd, frequency)
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

    panel = attach_caps(panel, bundle.prices, frequency)
    panel = panel.dropna(subset=[ALPHA, FWD_RET])
    return panel[list(ALIGNED_COLUMNS)].reset_index(drop=True)


# 信号与前视收益的对齐键。月频按 (资产, 自然月) 而非 (日期, 资产)：
# 信号落在月内哪一天、价格面板的月末是哪一天，两者不必逐字相等。
def _merge_forward(signals: pd.DataFrame, fwd: pd.DataFrame, frequency) -> pd.DataFrame:
    if not resolve(frequency).is_monthly:
        return signals.merge(fwd, on=[DATE, ASSET], how="left")
    left = signals.copy()
    left[_MONTH] = month_key(left[DATE])
    right = fwd.drop(columns=[DATE]).copy()
    right[_MONTH] = month_key(fwd[DATE])
    return left.merge(right, on=[ASSET, _MONTH], how="left").drop(columns=[_MONTH])
