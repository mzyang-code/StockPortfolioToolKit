# 可插拔数据源：文件读取 + 列映射 + dtype 归一，产出契约列
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .. import io
from ..config_schema import PriceSpec, ReferenceSpec, SignalSpec
from ..contracts import (
    ALPHA,
    ASSET,
    CAP,
    CLOSE,
    DATE,
    FREQ_DAILY,
    FREQ_PERIOD,
    FREQUENCY,
    FWD_RET,
    NAME,
    RET,
    SIGNAL,
    ContractError,
)
from ..registry import Registry

ALPHA_SOURCES: Registry = Registry("alpha source")
PRICE_SOURCES: Registry = Registry("price source")
REFERENCE_SOURCES: Registry = Registry("reference source")


class Source(ABC):
    def __init__(self, spec, variables: Optional[Mapping[str, str]] = None) -> None:
        self.spec = spec
        self.variables = dict(variables or {})

    @abstractmethod
    def load(self, **kwargs) -> pd.DataFrame:
        ...


class AlphaSource(Source):
    """产出 [date, asset, signal, alpha]（可选 fwd_ret）

    load() 会记录 rows_read / rows_dropped，供上游如实报告源文件的缺失率——
    dropna 默认打开，光看产出表永远是 0，看不出源文件到底有多脏。
    """

    rows_read: int = 0
    rows_dropped: int = 0


class PriceSource(Source):
    """产出 [date, asset, close, cap]"""


class ReferenceSource(Source):
    """产出 [date, name, ret, frequency]"""


# 取数入口：屏蔽「文件 vs 内存」的差别，返回 (可用列名, 报错上下文, 按列取数的函数)。
# 文件侧先 peek 表头（Arrow 只读 footer，10GB 面板也是常数开销），校验通过才真正读列。
def _open(spec, variables: Mapping[str, str]):
    if spec.frame is not None:
        frame = spec.frame
        if not isinstance(frame, pd.DataFrame):
            raise ContractError(f"frame 必须是 DataFrame，得到 {type(frame).__name__}")
        ctx = f"frame<{getattr(spec, 'name', 'prices')}>"
        return list(frame.columns), ctx, lambda cols: frame.loc[:, cols].copy()

    path = io.resolve_path(spec.path, variables)
    fmt = spec.format or io.infer_format(path)
    read_kwargs = getattr(spec, "read_kwargs", {})
    return (
        io.peek_columns(path, fmt),
        path.name,
        lambda cols: io.read_table(path, fmt, columns=cols, **read_kwargs),
    )


# 源表可用列名。文件只读表头，不载入数据，因此可用于「这份数据有没有 close / cap」这类探查
def available_columns(spec, variables: Mapping[str, str]) -> List[str]:
    available, _, _ = _open(spec, variables)
    return list(available)


# 源表能否提供某个契约列。判定与 _auto_map 同构：声明了 column_map 就以声明为准，
# 留空则看源表有无同名列。
def provides_column(spec, target: str, variables: Mapping[str, str]) -> bool:
    available = available_columns(spec, variables)
    if spec.column_map:
        source = spec.column_map.get(target)
        return bool(source) and source in available
    return target in available


# column_map 整体留空时，按契约列名在源表中同名匹配，列名已与契约一致的表因此不必写映射。
#
# 只认「整体留空」而非逐列补全：写了 column_map 就进入显式模式，此时遗漏某列是有意义的
# 声明而非疏忽——prices 不映射 close 正是「本面板无可用价格序列，只供市值与交易日历」的
# 表达方式（见 TablePriceSource.load 与 guide/prepare-data）。逐列补全会把这个开关废掉。
def _auto_map(
    column_map: dict, available: Sequence[str], targets: Sequence[str]
) -> dict:
    if column_map:
        return dict(column_map)
    return {t: t for t in targets if t in available}


# 取数 + 列名校验 + 只取需要的列，文件与内存两条路径共用
def _read_mapped(
    spec,
    variables: Mapping[str, str],
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> pd.DataFrame:
    available, ctx, fetch = _open(spec, variables)
    column_map = _auto_map(dict(spec.column_map), available, (*required, *optional))

    missing = [t for t in required if not column_map.get(t)]
    if missing:
        raise ContractError(
            f"{ctx}: 缺少必需列 {missing}；源列为 {available}。"
            f"源列名与之不同时请用 column_map 声明映射。"
        )

    wanted = [column_map[t] for t in required]
    for target in optional:
        source = column_map.get(target)
        if source and source in available:
            wanted.append(source)
        else:
            column_map.pop(target, None)

    unknown = [c for c in wanted if c not in available]
    if unknown:
        raise ContractError(f"{ctx}: 源列 {unknown} 不存在；实际列为 {available}")

    df = fetch(wanted)
    keep = {t: s for t, s in column_map.items() if s in df.columns}
    return io.apply_column_map(df, keep, ctx=ctx)


# 三类源各登记一次，四种来源共用同一套实现：取数差异已收敛进 _open，
# load() 之后的列映射、dtype 归一与缺失统计在文件与内存两条路径上完全一致。
@ALPHA_SOURCES.register("frame")
@ALPHA_SOURCES.register("feather")
@ALPHA_SOURCES.register("parquet")
@ALPHA_SOURCES.register("csv")
class TableAlphaSource(AlphaSource):
    spec: SignalSpec

    def load(self, **_) -> pd.DataFrame:
        df = _read_mapped(self.spec, self.variables, (DATE, ASSET, ALPHA), (FWD_RET,))
        df[DATE] = io.normalize_date(df[DATE])
        df[ASSET] = io.normalize_asset(df[ASSET])
        df[ALPHA] = io.normalize_float(df[ALPHA])
        if FWD_RET in df.columns:
            df[FWD_RET] = io.normalize_float(df[FWD_RET])
        self.rows_read = len(df)
        usable = df[[DATE, ASSET, ALPHA]].notna().all(axis=1).sum()
        self.rows_dropped = int(self.rows_read - usable)
        if self.spec.dropna:
            df = df.dropna(subset=[DATE, ASSET, ALPHA])
        df[SIGNAL] = self.spec.name
        cols = [DATE, ASSET, SIGNAL, ALPHA] + ([FWD_RET] if FWD_RET in df.columns else [])
        return df[cols].sort_values([DATE, ASSET]).reset_index(drop=True)


@PRICE_SOURCES.register("frame")
@PRICE_SOURCES.register("feather")
@PRICE_SOURCES.register("parquet")
@PRICE_SOURCES.register("csv")
class TablePriceSource(PriceSource):
    spec: PriceSpec

    # assets / start 由 Processor 下推，避免整块面板进内存
    def load(
        self,
        assets: Optional[Iterable[str]] = None,
        start: Optional[pd.Timestamp] = None,
        **_,
    ) -> pd.DataFrame:
        spec = self.spec
        # close 只在 engine.forward_return.source="prices" 时参与计算。显式声明了却对不上
        # 源列要报错，拼写错误不会被静默当成缺列；未声明则归入可选列——源表恰有同名 close
        # 时由 _auto_map 带入，没有则价格面板退化为市值与交易日历的来源。
        declared_close = bool(spec.column_map.get(CLOSE))
        required = (DATE, ASSET, CLOSE) if declared_close else (DATE, ASSET)
        optional = (CAP,) if declared_close else (CLOSE, CAP)
        df = _read_mapped(spec, self.variables, required, optional)
        df[DATE] = io.normalize_date(df[DATE])
        if start is not None:
            df = df[df[DATE] >= start]

        df[ASSET] = io.normalize_asset(df[ASSET])
        if assets is not None and spec.restrict_to_signal_assets:
            df = df[df[ASSET].isin(set(assets))]

        for column in (CLOSE, CAP):
            df[column] = (
                io.normalize_float(df[column])
                if column in df.columns
                else pd.Series(np.nan, index=df.index, dtype=np.float64)
            )
        out = df[[DATE, ASSET, CLOSE, CAP]].dropna(subset=[DATE, ASSET])
        return out.sort_values([ASSET, DATE]).reset_index(drop=True)


@REFERENCE_SOURCES.register("frame")
@REFERENCE_SOURCES.register("feather")
@REFERENCE_SOURCES.register("parquet")
@REFERENCE_SOURCES.register("csv")
class TableReferenceSource(ReferenceSource):
    spec: ReferenceSpec

    def load(self, **_) -> pd.DataFrame:
        freq = str(self.spec.frequency).lower()
        if freq not in (FREQ_DAILY, FREQ_PERIOD):
            raise ContractError(
                f"reference '{self.spec.name}': frequency 只能是 "
                f"'{FREQ_DAILY}' 或 '{FREQ_PERIOD}'，得到 '{self.spec.frequency}'"
            )
        df = _read_mapped(self.spec, self.variables, (DATE, RET))
        df[DATE] = io.normalize_date(df[DATE])
        df[RET] = io.normalize_float(df[RET])
        df = df.dropna(subset=[DATE, RET])
        df[NAME] = self.spec.name
        df[FREQUENCY] = freq
        return df[[DATE, NAME, RET, FREQUENCY]].sort_values(DATE).reset_index(drop=True)


# 内存表没有后缀可推，直接取 frame 分支；文件仍按 format 或后缀选实现
def _build(registry: Registry, spec, variables: Mapping[str, str]) -> Source:
    if spec.frame is not None:
        kind = "frame"
    else:
        kind = spec.format or io.infer_format(io.resolve_path(spec.path, variables))
    return registry.get(kind)(spec, variables)


def build_alpha_source(spec: SignalSpec, variables: Mapping[str, str]) -> AlphaSource:
    return _build(ALPHA_SOURCES, spec, variables)


def build_price_source(spec: PriceSpec, variables: Mapping[str, str]) -> PriceSource:
    return _build(PRICE_SOURCES, spec, variables)


def build_reference_source(spec: ReferenceSpec, variables: Mapping[str, str]) -> ReferenceSource:
    return _build(REFERENCE_SOURCES, spec, variables)
