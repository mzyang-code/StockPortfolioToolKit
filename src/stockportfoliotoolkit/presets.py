# 图表与数据表的预设：把常用组合收敛成一个名字
#
# charts.py 只注册了一种图表类型（cumulative_log_return），实际用到的两张图区别仅在
# buckets 与 color_mode——一张比较各策略的多空腿，一张拆解单一策略的分位内部结构。
# config_schema 的 is_decile_view / wants_split_by_signal 已对这两种用法做过特判，
# 这里把它们各自固化成一个名字。
#
# 分位图的桶列表按 n_buckets 动态生成：手写配置时这串 "0".."9" 与 engine.n_buckets
# 分处两个文件，改动一处而忘了另一处，图与数据就对不上了。
from __future__ import annotations

from typing import Dict, List

from .config_schema import ChartSpec, TableSpec
from .contracts import LONG_SHORT_BUCKET, REFERENCE_BUCKET

LONG_SHORT = "long_short"
DECILES = "deciles"

CHART_PRESETS = (LONG_SHORT, DECILES)
TABLE_PRESETS = ("summary", "turnover", "ic")


def _bucket_labels(n_buckets: int) -> List[str]:
    return [str(i) for i in range(int(n_buckets))]


def chart_preset(kind: str, n_buckets: int, **overrides) -> ChartSpec:
    """按预设名产出 ChartSpec；overrides 直接透传给 ChartSpec，供单图临时调整。"""
    kind = str(kind).strip().lower()
    if kind == LONG_SHORT:
        # 多空腿与外部基准同图对比，零线便于读出盈亏分界
        base: Dict = {
            "name": LONG_SHORT,
            "buckets": [LONG_SHORT_BUCKET, REFERENCE_BUCKET],
            "color_mode": "palette",
            "show_baseline": True,
        }
    elif kind == DECILES:
        # 分位走色阶、多空腿单独强调；两列图例容纳十个分位
        base = {
            "name": DECILES,
            "buckets": [*_bucket_labels(n_buckets), LONG_SHORT_BUCKET],
            "color_mode": "gradient",
            "legend_ncol": 2,
        }
    else:
        raise ValueError(
            f"未知的图表预设 '{kind}'；可用项为 {list(CHART_PRESETS)}。"
            f"需要更细的控制请直接构造 ChartSpec 并传给 Visualizer。"
        )
    base.update(overrides)
    return ChartSpec(**base)


def table_preset(kind: str, **overrides) -> TableSpec:
    """按 tables.py 已注册的类型产出 TableSpec。"""
    kind = str(kind).strip().lower()
    if kind not in TABLE_PRESETS:
        raise ValueError(f"未知的数据表预设 '{kind}'；可用项为 {list(TABLE_PRESETS)}")
    base: Dict = {"name": {"summary": "metrics", "turnover": "turnover", "ic": "ic"}[kind],
                  "type": kind}
    base.update(overrides)
    return TableSpec(**base)
