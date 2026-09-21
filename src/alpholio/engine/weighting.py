# 权重器：截面内把成分股折算成一组和为 1 的权重
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..contracts import CAP
from ..registry import Registry

WEIGHTERS: Registry = Registry("weighter")


class Weighter(ABC):
    name: str = ""

    def __init__(self, **options: Any) -> None:
        self.options = options

    # 结果表里的 weight 值，默认取配置名的大写形式
    @property
    def label(self) -> str:
        return self.name.upper()

    # 返回与 frame 等长、和为 1 的权重；无法计算时返回 None（该桶收益记 NaN）
    @abstractmethod
    def weights(self, frame: pd.DataFrame) -> Optional[np.ndarray]:
        ...


@WEIGHTERS.register()
class EqualWeighter(Weighter):
    name = "ew"

    def weights(self, frame: pd.DataFrame) -> Optional[np.ndarray]:
        n = len(frame)
        return np.full(n, 1.0 / n) if n else None


# 缺市值或市值非正的成分股权重记 0，等价于剔除后重新归一；
# 不裁负值会让 Σcap 变小甚至跨零，权重随之出现杠杆与反向暴露
@WEIGHTERS.register()
class CapWeighter(Weighter):
    name = "vw"

    def weights(self, frame: pd.DataFrame) -> Optional[np.ndarray]:
        cap = frame[CAP].to_numpy(dtype=np.float64, copy=True)
        cap[~(np.isfinite(cap) & (cap > 0.0))] = 0.0
        total = cap.sum()
        return cap / total if total > 0 else None


def build_weighter(name: str, options: Optional[Dict[str, Any]] = None) -> Weighter:
    return WEIGHTERS.get(name)(**(options or {}))
