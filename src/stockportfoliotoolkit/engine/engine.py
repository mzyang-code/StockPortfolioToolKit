# ② Portfolio Engine：面板 → 分桶 → 组合收益长表
from __future__ import annotations

import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..config_schema import EngineConfig, HoldingPeriodWarning
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
from ..frequency import DAILY, MONTH_COLUMN, month_key, resolve
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
        _warn_on_overlap(bundle, cfg)
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
            meta=self._describe(returns, members, bundle.frequency),
        )

    # 外部基准按持有期折算后，对每个权重方案各复制一行，方便下游统一过滤
    def _reference_returns(self, bundle: InputBundle) -> pd.DataFrame:
        cfg = self.cfg
        bar = resolve(bundle.frequency)
        frames: List[pd.DataFrame] = []
        for name, grp in bundle.references.groupby(NAME, sort=True):
            # references[].frequency 说的是基准序列本身的观测频率，与面板的 bar 长度
            # （bundle.frequency）是两件事：前者决定要不要复利，后者决定窗口有多长
            if str(grp[FREQUENCY].iloc[0]).lower() == FREQ_DAILY:
                # 基准与组合必须测同一个窗口才可比，因此这里用 horizon 而非 holding_days
                series = _compound(
                    grp, bundle.calendar, cfg.forward_return.horizon, cfg.reference_lag, bar
                )
            else:
                series = _align_period(grp, bundle.calendar, bar)
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

    def _describe(
        self, returns: pd.DataFrame, members: pd.DataFrame, frequency: str
    ) -> Dict:
        spec = self.cfg.long_short
        long_bucket, short_bucket = long_short_buckets(self.cfg)
        return {
            # 年化基数由它决定，Analyzer 从这里取；holding_days 的单位同样随它
            "frequency": resolve(frequency).name,
            "holding_days": int(self.cfg.holding_days),
            "forward_horizon": int(self.cfg.forward_return.horizon),
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


# 调仓间隔与测量期不等时，逐期收益不是首尾相接的：间隔 < 测量期则窗口互相重叠，
# 把它们当独立期累乘会重复计入同一段行情；间隔 > 测量期则期间有空仓缺口。
# 两种情况都只告警不拦截——用户可能确实要看重叠窗口的信息系数。
def _warn_on_overlap(bundle: InputBundle, cfg: EngineConfig) -> None:
    calendar = bundle.calendar
    if len(calendar) < 3:
        return
    frequency = resolve(bundle.frequency)
    stride = _calendar_stride(bundle, frequency)
    horizon = int(cfg.forward_return.horizon)
    if stride is None or stride <= 0 or stride == horizon:
        return
    kind = "互相重叠" if stride < horizon else "之间存在空仓缺口"
    warnings.warn(
        f"调仓间隔约 {stride} 个{frequency.unit}，而 forward_return.horizon={horizon}："
        f"相邻两期的持有窗口{kind}。净值曲线与 total_equity / max_drawdown "
        f"按逐期累乘计算，在这种口径下会失真（重叠时同一段行情被重复计入）。"
        f"通常应让 input.calendar.rebalance_freq 与 horizon 相等。",
        HoldingPeriodWarning,
        stacklevel=3,
    )


# 相邻调仓日的间隔（中位数），单位与频率一致：月频数自然月，日频数价格面板上的交易日
def _calendar_stride(bundle: InputBundle, frequency) -> Optional[int]:
    calendar = pd.DatetimeIndex(bundle.calendar)
    if resolve(frequency).is_monthly:
        return int(np.median(np.diff(month_key(calendar))))
    trading_days = pd.DatetimeIndex(sorted(pd.unique(bundle.prices[DATE])))
    pos = trading_days.get_indexer(calendar)
    pos = pos[pos >= 0]
    if len(pos) < 3:
        return None
    return int(np.median(np.diff(pos)))


# 日频基准复利成持有期收益。窗口口径随面板频率：
#   日频：[锚点+lag, 锚点+lag+horizon) 共 horizon 个交易日
#   月频：窗口末端取「锚点所在月 + horizon 个月」的月末，lag>=1 时 (锚点, 末端]，
#         lag=0 时 [锚点, 末端)
# 两种口径下窗口数据不足都跳过该锚点，不产出截断窗口算出的收益。
def _compound(
    reference: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    holding_days: int,
    lag: int,
    frequency=DAILY,
) -> pd.DataFrame:
    h, lag = int(holding_days), int(lag)
    if resolve(frequency).is_monthly:
        return _compound_monthly(reference, calendar, h, lag)
    dates = reference[DATE].to_numpy()
    rets = reference[RET].to_numpy(dtype=np.float64)
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


# 月频窗口按自然月边界切，不按基准序列的行数：基准的交易日历与面板未必一致，
# 数行数会让窗口逐月漂移。
#
# 末端取目标月的月末而不是「锚点 + h 个月」那一天：锚点通常落在月内最后一个交易日
# （如 3 月 29 日），加一个月得到 4 月 29 日，会把 4 月最后一两天的行情漏在窗口外，
# 而组合那一期测的是 3 月末收盘 → 4 月末收盘。两者必须是同一个窗口才可比。
def _compound_monthly(
    reference: pd.DataFrame, calendar: pd.DatetimeIndex, h: int, lag: int
) -> pd.DataFrame:
    if lag not in (0, 1):
        raise ContractError(
            f"月度口径下 engine.reference_lag 只能取 0（含锚点当日）或 1（从次日起），"
            f"得到 {lag}：自然月窗口里没有「第 {lag} 个交易日开始」这回事。"
        )
    dates = reference[DATE].to_numpy()
    rets = reference[RET].to_numpy(dtype=np.float64)
    if len(dates) == 0:
        return pd.DataFrame(columns=[DATE, RET])
    side = "right" if lag else "left"
    rows = []
    for anchor in calendar:
        end = (anchor + pd.DateOffset(months=h) + pd.offsets.MonthEnd(0)).to_datetime64()
        # 数据没覆盖到窗口末端就跳过。月末恰为周末时末期基准会因此缺一期——
        # 这比把半个月的收益当成整月报出来要好
        if end > dates[-1]:
            continue
        lo = int(np.searchsorted(dates, anchor.to_datetime64(), side=side))
        hi = int(np.searchsorted(dates, end, side=side))
        window = rets[lo:hi]
        if len(window) == 0:
            continue
        rows.append({DATE: anchor, RET: float(np.prod(1.0 + window) - 1.0)})
    return pd.DataFrame(rows, columns=[DATE, RET])


# 已是周期收益的基准直接对齐调仓日历。月频按自然月对齐（每月取最后一行）：
# 基准的月末日期与面板的月末日期未必是同一天，逐字相等会让整条基准对不上而静默消失。
def _align_period(
    reference: pd.DataFrame, calendar: pd.DatetimeIndex, frequency
) -> pd.DataFrame:
    if not resolve(frequency).is_monthly:
        return reference[reference[DATE].isin(calendar)][[DATE, RET]]
    anchors = pd.DataFrame({DATE: pd.DatetimeIndex(calendar)})
    anchors[MONTH_COLUMN] = month_key(anchors[DATE])
    rows = reference.sort_values(DATE).copy()
    rows[MONTH_COLUMN] = month_key(rows[DATE])
    rows = rows.groupby(MONTH_COLUMN, sort=False, as_index=False).tail(1)
    merged = anchors.merge(rows[[MONTH_COLUMN, RET]], on=MONTH_COLUMN, how="inner")
    return merged[[DATE, RET]]
