# ① Input Processor：读取 → 标准化 → 建调仓日历 → 打包 InputBundle
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..config import InputConfig
from ..contracts import ALPHA, ASSET, DATE, NAME, SIGNAL, ContractError, InputBundle
from .sources import build_alpha_source, build_price_source, build_reference_source


class InputProcessor:
    def __init__(self, cfg: InputConfig) -> None:
        if not cfg.signals:
            raise ContractError("input.signals 为空，至少需要一个 alpha 信号源")
        self.cfg = cfg

    # 唯一出口
    def run(self) -> InputBundle:
        cfg = self.cfg
        signals = self._load_signals()
        first, last = _bounds(cfg.calendar, signals)
        prices = self._load_prices(signals, first)
        base = signals if str(cfg.calendar.source).lower() == "signals" else prices
        trading_days = pd.DatetimeIndex(sorted(pd.unique(prices[DATE])))
        calendar, stride_info = _build_calendar(base, first, last, cfg.calendar, trading_days)
        references = self._load_references()
        meta = self._describe(signals, prices, references, calendar)
        meta["calendar"].update(stride_info)
        return InputBundle(
            signals=signals,
            prices=prices,
            calendar=calendar,
            references=references,
            meta=meta,
        )

    def _load_signals(self) -> pd.DataFrame:
        frames = [build_alpha_source(s, self.cfg.vars).load() for s in self.cfg.signals]
        names = [s.name for s in self.cfg.signals]
        if len(set(names)) != len(names):
            raise ContractError(f"input.signals 存在重名: {names}")
        merged = pd.concat(frames, ignore_index=True)
        if merged.empty:
            raise ContractError("所有 alpha 信号源均为空")
        return merged.sort_values([SIGNAL, DATE, ASSET]).reset_index(drop=True)

    # 价格面板从首个调仓日读起：前视收益往后取数，无需历史缓冲
    def _load_prices(
        self, signals: pd.DataFrame, first: Optional[pd.Timestamp]
    ) -> pd.DataFrame:
        spec = self.cfg.prices
        assets = signals[ASSET].unique() if spec.restrict_to_signal_assets else None
        prices = build_price_source(spec, self.cfg.vars).load(assets=assets, start=first)
        if prices.empty:
            raise ContractError(f"价格面板在过滤后为空: {spec.path}")
        duplicated = prices.duplicated(subset=[DATE, ASSET]).sum()
        if duplicated:
            raise ContractError(
                f"价格面板存在 {duplicated:,} 行重复的 (date, asset)，"
                f"会让市值关联膨胀，请先去重: {spec.path}"
            )
        return prices

    def _load_references(self) -> Optional[pd.DataFrame]:
        if not self.cfg.references:
            return None
        frames = [build_reference_source(r, self.cfg.vars).load() for r in self.cfg.references]
        return pd.concat(frames, ignore_index=True)

    def _describe(self, signals, prices, references, calendar) -> Dict:
        per_signal = {}
        for name, grp in signals.groupby(SIGNAL, sort=True):
            covered = grp[DATE].isin(calendar).sum()
            per_signal[str(name)] = {
                "rows": int(len(grp)),
                "assets": int(grp[ASSET].nunique()),
                "first": str(grp[DATE].min().date()),
                "last": str(grp[DATE].max().date()),
                "rows_on_calendar": int(covered),
                "alpha_na_rate": float(grp[ALPHA].isna().mean()),
            }
        return {
            "signals": per_signal,
            "prices": {
                "rows": int(len(prices)),
                "assets": int(prices[ASSET].nunique()),
                "first": str(prices[DATE].min().date()),
                "last": str(prices[DATE].max().date()),
            },
            "references": sorted(references[NAME].unique().tolist()) if references is not None else [],
            "calendar": {
                "periods": int(len(calendar)),
                "first": str(calendar[0].date()),
                "last": str(calendar[-1].date()),
                "rebalance_freq": int(self.cfg.calendar.rebalance_freq),
            },
        }


def _bounds(calendar_cfg, signals: pd.DataFrame):
    first = pd.Timestamp(calendar_cfg.first_rebalance) if calendar_cfg.first_rebalance else None
    last = pd.Timestamp(calendar_cfg.last_rebalance) if calendar_cfg.last_rebalance else None
    if first is None:
        first = pd.Timestamp(signals[DATE].min())
    return first, last


# 按 freq 抽稀，起点是首个 >= first_rebalance 的日期；
# auto_stride 下若信号日历原生间隔已 >= freq 则不再抽稀（否则周期数会被再砍 freq 倍）
def _build_calendar(
    base: pd.DataFrame,
    first: Optional[pd.Timestamp],
    last: Optional[pd.Timestamp],
    cfg,
    trading_days: pd.DatetimeIndex,
):
    freq = int(cfg.rebalance_freq)
    if freq < 1:
        raise ContractError(f"calendar.rebalance_freq 必须 >= 1，得到 {freq}")
    dates = pd.DatetimeIndex(sorted(pd.unique(base[DATE].dropna())))
    if first is not None:
        dates = dates[dates >= first]
    if last is not None:
        dates = dates[dates <= last]
    if len(dates) == 0:
        raise ContractError("调仓日历为空：检查 first_rebalance/last_rebalance 与数据区间是否重叠")

    native = _native_stride(dates, trading_days)
    step = 1 if (cfg.auto_stride and native >= freq) else freq
    return dates[::step], {"native_stride": native, "applied_stride": step}


# 信号日期在交易日历上的相邻位置差（中位数），单位为交易日
def _native_stride(dates: pd.DatetimeIndex, trading_days: pd.DatetimeIndex) -> int:
    if len(dates) < 2 or len(trading_days) == 0:
        return 1
    pos = trading_days.get_indexer(dates)
    pos = pos[pos >= 0]
    if len(pos) < 2:
        return 1
    return max(1, int(np.median(np.diff(pos))))
