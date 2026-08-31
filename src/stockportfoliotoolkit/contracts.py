# 模块间数据契约：统一列名 + 三份不可变产物
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

import pandas as pd

# 全局列名唯一真源，任何模块都不得自造字面量
# 左侧是代码里的语义名，右侧是所有产物表实际出现的列名
DATE = "date"
ASSET = "id"
SIGNAL = "signal_model"
ALPHA = "alpha"
CLOSE = "close"
CAP = "cap"
FWD_RET = "fwd_ret"
BUCKET = "bucket"
WEIGHT = "weight"
RET = "ret"
N_NAMES = "count"
NAME = "name"
FREQUENCY = "frequency"
EQUITY = "equity"
CUM_LOG_RET = "cum_log_ret"
IC = "ic"
TURNOVER = "turnover"

# 特殊桶标签：多空组合 / 外部基准
LONG_SHORT_BUCKET = "H-L"
REFERENCE_BUCKET = "REF"

# 外部基准的原始频率：daily 需按持有期复利，period 直接按日历对齐
FREQ_DAILY = "daily"
FREQ_PERIOD = "period"

SIGNAL_COLUMNS = (DATE, ASSET, SIGNAL, ALPHA)
PRICE_COLUMNS = (DATE, ASSET, CLOSE, CAP)
REFERENCE_COLUMNS = (DATE, NAME, RET, FREQUENCY)
RETURN_COLUMNS = (DATE, SIGNAL, BUCKET, WEIGHT, RET, N_NAMES)
MEMBER_COLUMNS = (DATE, SIGNAL, ASSET, BUCKET)
ALIGNED_COLUMNS = (DATE, ASSET, SIGNAL, ALPHA, FWD_RET, CAP)


class ContractError(ValueError):
    """上下游交接处的结构性错误"""


# 分位桶按数值升序，H-L / REF 等特殊桶排在最后
def bucket_rank(bucket) -> float:
    text = str(bucket)
    return float(text) if text.lstrip("-").isdigit() else float("inf")


# 结果表统一排序：分组键 → 加权 → 桶
def sort_by_bucket(frame: pd.DataFrame, group_keys: Sequence[str] = ()) -> pd.DataFrame:
    if frame.empty or BUCKET not in frame.columns:
        return frame.reset_index(drop=True)
    keys = [k for k in group_keys if k in frame.columns]
    ranked = frame.assign(_rank=frame[BUCKET].map(bucket_rank))
    return (
        ranked.sort_values([*keys, "_rank", BUCKET])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )


# 校验列齐全，报错带来源上下文
def require_columns(df: pd.DataFrame, columns: Sequence[str], ctx: str) -> pd.DataFrame:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ContractError(
            f"{ctx}: 缺少列 {missing}；实际列为 {list(df.columns)}"
        )
    return df


@dataclass(frozen=True)
class InputBundle:
    """Input Processor 的唯一出口"""

    signals: pd.DataFrame
    prices: pd.DataFrame
    calendar: pd.DatetimeIndex
    references: Optional[pd.DataFrame] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_columns(self.signals, SIGNAL_COLUMNS, "InputBundle.signals")
        require_columns(self.prices, PRICE_COLUMNS, "InputBundle.prices")
        if self.references is not None:
            require_columns(self.references, REFERENCE_COLUMNS, "InputBundle.references")
        if len(self.calendar) == 0:
            raise ContractError("InputBundle.calendar: 调仓日历为空")

    @property
    def signal_names(self) -> list:
        return sorted(self.signals[SIGNAL].unique().tolist())


@dataclass(frozen=True)
class EngineResult:
    """Portfolio Engine 的唯一出口"""

    returns: pd.DataFrame
    members: pd.DataFrame
    aligned: pd.DataFrame
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_columns(self.returns, RETURN_COLUMNS, "EngineResult.returns")
        require_columns(self.members, MEMBER_COLUMNS, "EngineResult.members")
        require_columns(self.aligned, ALIGNED_COLUMNS, "EngineResult.aligned")

    @property
    def weights(self) -> list:
        return sorted(self.returns[WEIGHT].unique().tolist())


@dataclass(frozen=True)
class AnalysisResult:
    """Analyzer 的唯一出口"""

    summary: pd.DataFrame
    curves: pd.DataFrame
    turnover: pd.DataFrame
    ic: pd.DataFrame
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_columns(self.summary, (SIGNAL, BUCKET, WEIGHT), "AnalysisResult.summary")
        require_columns(self.curves, (DATE, SIGNAL, BUCKET, WEIGHT), "AnalysisResult.curves")


# 长表转回 stock_rag_v1 的宽表格式（anchor_date/decile/ew_ret/vw_ret/...）
def to_legacy_wide(
    returns: pd.DataFrame,
    weight_aliases: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    aliases = weight_aliases or {"EW": "ew_ret", "VW": "vw_ret"}
    wide = returns.pivot_table(
        index=[DATE, SIGNAL, BUCKET], columns=WEIGHT, values=RET, aggfunc="first"
    ).reset_index()
    wide.columns.name = None
    if N_NAMES in returns.columns:
        names = returns.groupby([DATE, SIGNAL, BUCKET], sort=False)[N_NAMES].max().reset_index()
        wide = wide.merge(names, on=[DATE, SIGNAL, BUCKET], how="left")
    # legacy 侧沿用 stock_rag_v1 的列名，不跟随包内改名
    wide = wide.rename(
        columns={**aliases, DATE: "anchor_date", BUCKET: "decile",
                 SIGNAL: "signal", N_NAMES: "n_names"}
    )
    ordered = ["anchor_date", "signal", "decile"]
    ordered += [c for c in aliases.values() if c in wide.columns]
    ordered += [c for c in ("n_names",) if c in wide.columns]
    return wide[ordered].sort_values(["decile", "anchor_date"]).reset_index(drop=True)
