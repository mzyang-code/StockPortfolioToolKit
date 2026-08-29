# 表格：过滤 + 百分比换算，保持数值型以便下游再加工
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..config import TableSpec
from ..contracts import BUCKET, SIGNAL, WEIGHT, AnalysisResult, sort_by_bucket
from ..registry import Registry

TABLES: Registry = Registry("table")


class Table(ABC):
    name: str = ""

    @abstractmethod
    def build(self, analysis: AnalysisResult, spec: TableSpec) -> pd.DataFrame:
        ...


@TABLES.register()
class SummaryTable(Table):
    name = "summary"

    def build(self, analysis: AnalysisResult, spec: TableSpec) -> pd.DataFrame:
        data = _filter(analysis.summary, spec)
        for column in spec.percent_columns:
            if column in data.columns:
                data[f"{column}_pct"] = data[column] * 100.0
                data = data.drop(columns=[column])
        numeric = data.select_dtypes("number").columns
        data[numeric] = data[numeric].round(spec.decimals)
        return sort_by_bucket(data, [SIGNAL, WEIGHT])


@TABLES.register()
class TurnoverTable(Table):
    name = "turnover"

    def build(self, analysis: AnalysisResult, spec: TableSpec) -> pd.DataFrame:
        return _filter(analysis.turnover, spec).reset_index(drop=True)


@TABLES.register()
class ICTable(Table):
    name = "ic"

    def build(self, analysis: AnalysisResult, spec: TableSpec) -> pd.DataFrame:
        return _filter(analysis.ic, spec).reset_index(drop=True)


def _filter(frame: pd.DataFrame, spec: TableSpec) -> pd.DataFrame:
    data = frame.copy()
    for column, wanted in ((BUCKET, spec.buckets), (WEIGHT, spec.weights), (SIGNAL, spec.signals)):
        if wanted and column in data.columns:
            data = data[data[column].isin(wanted)]
    return data


def build_table(kind: str) -> Table:
    return TABLES.get(kind)()
