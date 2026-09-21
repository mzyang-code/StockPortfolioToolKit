# 数据频率：一根 bar 代表多长，以及由此决定的单位、年化基数与「第 n 期」的取法
#
# 全包只此一处定义「一期有多长的单位」。日历抽稀、前视收益测量、基准复利窗口与年化
# 折算四处都从这里取，声明则只在 input.frequency 一个地方。
#
# 与 contracts.FREQ_DAILY / FREQ_PERIOD 不是一件事：那两个说的是**外部基准序列**本身
# 是日频观测还是已经折算成周期收益，作用范围限于 references[]；这里说的是**整份面板**
# 的 bar 有多长，决定上述四处的单位。
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from .contracts import ContractError

DAILY = "daily"
MONTHLY = "monthly"

# 自然月序号的临时列名。只在按月对齐的几次 merge 中间存在，不进任何产物表
MONTH_COLUMN = "_month"


@dataclass(frozen=True)
class Frequency:
    """一种数据频率的全部口径常量"""

    name: str
    unit: str  # 报错与告警里「多少个 X」的那个 X
    bars_per_year: float  # 年化基数。日频可由 analyzer.trading_days_per_year 覆盖

    @property
    def is_monthly(self) -> bool:
        return self.name == MONTHLY


FREQUENCIES = {
    DAILY: Frequency(name=DAILY, unit="交易日", bars_per_year=252.0),
    MONTHLY: Frequency(name=MONTHLY, unit="月", bars_per_year=12.0),
}


# 取值可以是频率名，也可以是已解析好的 Frequency（幂等），调用方不必先判类型
def resolve(name) -> Frequency:
    if isinstance(name, Frequency):
        return name
    key = str(name).lower()
    if key not in FREQUENCIES:
        raise ContractError(
            f"未知的数据频率 {name!r}；可用值为 {sorted(FREQUENCIES)}。"
            f"该项声明于 input.frequency，决定 rebalance_freq / horizon / holding_days "
            f"的单位与年化基数。"
        )
    return FREQUENCIES[key]


# 自然月序号：year * 12 + month。相邻月差 1，跨年不断档，可直接做差与平移。
# 用它而不是 pandas 的 Period，是为了能在 merge 与 numpy 运算里当普通整数用。
def month_key(dates) -> np.ndarray:
    index = pd.DatetimeIndex(pd.Series(dates).to_numpy())
    return (index.year.to_numpy() * 12 + index.month.to_numpy()).astype(np.int64)


# 每个 (分组键..., 自然月) 取日期最靠后的一行，即该月的月末观测。
# 月频口径下的 close 与 cap 都从这里取：一个月只认一个值，月内哪天调仓不影响取数。
def last_per_month(
    frame: pd.DataFrame, keys: Sequence[str], date_column: str, month_column: str
) -> pd.DataFrame:
    out = frame.copy()
    out[month_column] = month_key(out[date_column])
    ordered = out.sort_values([*keys, month_column, date_column])
    return ordered.groupby([*keys, month_column], sort=False, as_index=False).tail(1)
