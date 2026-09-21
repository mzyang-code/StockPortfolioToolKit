# 表格读写、路径变量展开、列名映射与 dtype 归一
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SUFFIX_FORMATS = {
    ".feather": "feather",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".csv": "csv",
    ".gz": "csv",
    ".zip": "csv",
    ".txt": "csv",
}


# ${VAR} 优先取配置 vars，其次环境变量
def resolve_path(raw: str, variables: Optional[Mapping[str, str]] = None) -> Path:
    variables = variables or {}

    def substitute(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        if key in os.environ:
            return os.environ[key]
        raise KeyError(f"路径变量 ${{{key}}} 未定义（既不在 config.vars 也不在环境变量中）")

    return Path(_VAR_PATTERN.sub(substitute, str(raw))).expanduser()


def infer_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".gz", ".zip") and len(path.suffixes) >= 2:
        suffix = path.suffixes[-2].lower()
    fmt = _SUFFIX_FORMATS.get(suffix)
    if fmt is None:
        raise ValueError(f"无法从后缀推断格式: {path.name}，请在配置中显式指定 format")
    return fmt


# 只读表头，用于在加载 10GB 级面板前校验列名
def peek_columns(path: Path, fmt: Optional[str] = None) -> List[str]:
    path = Path(path)
    fmt = (fmt or infer_format(path)).lower()
    if fmt == "feather":
        import pyarrow as pa
        import pyarrow.ipc as ipc

        try:  # Arrow IPC 只读 footer，10GB 面板也是常数开销
            with pa.memory_map(str(path)) as src:
                return list(ipc.open_file(src).schema.names)
        except pa.ArrowInvalid:  # feather v1 回退
            import pyarrow.feather as feather

            return list(feather.read_table(path, memory_map=True).schema.names)
    if fmt == "parquet":
        import pyarrow.parquet as parquet

        return list(parquet.read_schema(path).names)
    return list(pd.read_csv(path, nrows=0).columns)


# 统一读入口，columns 下推到 feather/parquet 以省内存
def read_table(
    path: Path,
    fmt: Optional[str] = None,
    columns: Optional[Sequence[str]] = None,
    **kwargs,
) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在: {path}")
    fmt = (fmt or infer_format(path)).lower()
    cols = list(columns) if columns else None
    if fmt == "feather":
        return pd.read_feather(path, columns=cols, **kwargs)
    if fmt == "parquet":
        return pd.read_parquet(path, columns=cols, **kwargs)
    if fmt == "csv":
        return pd.read_csv(path, usecols=cols, **kwargs)
    raise ValueError(f"不支持的格式: {fmt}")


def write_table(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = infer_format(path)
    if fmt == "feather":
        df.reset_index(drop=True).to_feather(path)
    elif fmt == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


# 源列名 → 包内统一列名；缺失的源列直接报错
def apply_column_map(
    df: pd.DataFrame,
    column_map: Mapping[str, str],
    ctx: str,
    optional: Iterable[str] = (),
) -> pd.DataFrame:
    optional = set(optional)
    rename: Dict[str, str] = {}
    for target, source in column_map.items():
        if source is None:
            continue
        if source not in df.columns:
            if target in optional:
                continue
            raise KeyError(
                f"{ctx}: 源列 '{source}'（映射为 '{target}'）不存在；实际列为 {list(df.columns)}"
            )
        rename[source] = target
    out = df.rename(columns=rename)
    keep = [t for t in column_map if t in out.columns]
    return out[keep].copy()


def normalize_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").astype("datetime64[ns]")


# 资产 ID 统一为字符串，浮点型整数 ID（1001.0）先归整避免错位
def normalize_asset(series: pd.Series) -> pd.Series:
    if pd.api.types.is_float_dtype(series):
        as_int = series.round().astype("Int64")
        return as_int.astype(str)
    if pd.api.types.is_integer_dtype(series):
        return series.astype("Int64").astype(str)
    return series.astype(str).str.strip()


def normalize_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(np.float64)
