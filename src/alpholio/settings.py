# 全局默认设置：高频复用、低频改动的项集中在此，不占用 backtest() 的参数表
#
# 样式字段有五十余个，逐个铺进函数签名会把真正决定口径的参数淹没。改一次全局生效，
# 单张图的临时偏好仍可在 plot() 上就地覆盖。
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from .config_schema import StyleSpec


class Settings:
    """进程级默认值。

    ``style`` 是可变对象，直接改字段即可，改动对之后的每次渲染生效：

        alp.settings.style.figsize = (10, 6)
        alp.settings.style.dpi = 300
        alp.settings.style.palette = {"MOM": "#1f77b4"}
        alp.settings.reset()          # 复原到出厂默认
    """

    style: StyleSpec
    # backtest(...) 未指定落点、且输入为内存 DataFrame 时的兜底产物目录。
    # 留空则不猜测落点，由 save() 显式给出。
    output_dir: Optional[str]

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.style = StyleSpec()
        self.output_dir = None

    # 取一份独立副本：写进某个 config 后，后续对全局的改动不应回溯影响它
    def style_copy(self) -> StyleSpec:
        return replace(self.style)

    def __repr__(self) -> str:
        return f"Settings(style=StyleSpec(...), output_dir={self.output_dir!r})"


settings = Settings()
