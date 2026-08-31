# 可插拔数据源：文件读取 + 列映射 + dtype 归一，产出契约列
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Mapping, Optional, Sequence

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


# 读文件 + 列名校验 + 只取需要的列
def _read_mapped(
    spec,
    variables: Mapping[str, str],
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> pd.DataFrame:
    path = io.resolve_path(spec.path, variables)
    fmt = spec.format or io.infer_format(path)
    column_map = dict(spec.column_map)
    missing = [t for t in required if not column_map.get(t)]
    if missing:
        raise ContractError(f"{spec.path}: column_map 缺少必需映射 {missing}")

    available = io.peek_columns(path, fmt)
    wanted = [column_map[t] for t in required]
    for target in optional:
        source = column_map.get(target)
        if source and source in available:
            wanted.append(source)
        else:
            column_map.pop(target, None)

    unknown = [c for c in wanted if c not in available]
    if unknown:
        raise ContractError(f"{path.name}: 源列 {unknown} 不存在；实际列为 {available}")

    df = io.read_table(path, fmt, columns=wanted, **getattr(spec, "read_kwargs", {}))
    keep = {t: s for t, s in column_map.items() if s in df.columns}
    return io.apply_column_map(df, keep, ctx=path.name)


@ALPHA_SOURCES.register("feather")
@ALPHA_SOURCES.register("parquet")
@ALPHA_SOURCES.register("csv")
class FileAlphaSource(AlphaSource):
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


@PRICE_SOURCES.register("feather")
@PRICE_SOURCES.register("parquet")
@PRICE_SOURCES.register("csv")
class FilePriceSource(PriceSource):
    spec: PriceSpec

    # assets / start 由 Processor 下推，避免整块面板进内存
    def load(
        self,
        assets: Optional[Iterable[str]] = None,
        start: Optional[pd.Timestamp] = None,
        **_,
    ) -> pd.DataFrame:
        spec = self.spec
        df = _read_mapped(spec, self.variables, (DATE, ASSET, CLOSE), (CAP,))
        df[DATE] = io.normalize_date(df[DATE])
        if start is not None:
            df = df[df[DATE] >= start]

        df[ASSET] = io.normalize_asset(df[ASSET])
        if assets is not None and spec.restrict_to_signal_assets:
            df = df[df[ASSET].isin(set(assets))]

        df[CLOSE] = io.normalize_float(df[CLOSE])
        df[CAP] = (
            io.normalize_float(df[CAP])
            if CAP in df.columns
            else pd.Series(np.nan, index=df.index, dtype=np.float64)
        )
        out = df[[DATE, ASSET, CLOSE, CAP]].dropna(subset=[DATE, ASSET])
        return out.sort_values([ASSET, DATE]).reset_index(drop=True)


@REFERENCE_SOURCES.register("feather")
@REFERENCE_SOURCES.register("parquet")
@REFERENCE_SOURCES.register("csv")
class FileReferenceSource(ReferenceSource):
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


def _build(registry: Registry, spec, variables: Mapping[str, str]) -> Source:
    kind = spec.format or io.infer_format(io.resolve_path(spec.path, variables))
    return registry.get(kind)(spec, variables)


def build_alpha_source(spec: SignalSpec, variables: Mapping[str, str]) -> AlphaSource:
    return _build(ALPHA_SOURCES, spec, variables)


def build_price_source(spec: PriceSpec, variables: Mapping[str, str]) -> PriceSource:
    return _build(PRICE_SOURCES, spec, variables)


def build_reference_source(spec: ReferenceSpec, variables: Mapping[str, str]) -> ReferenceSource:
    return _build(REFERENCE_SOURCES, spec, variables)
