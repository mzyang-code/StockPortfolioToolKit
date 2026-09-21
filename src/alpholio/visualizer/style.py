# 配色与线型：全部由 visualizer.json 驱动，代码内不写死颜色
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib as mpl

from ..config_schema import StyleSpec
from ..contracts import REFERENCE_BUCKET, bucket_rank

Line = Tuple[str, str]  # (signal, bucket)

PALETTE_MODE = "palette"
GRADIENT_MODE = "gradient"

# 默认图例文案：gradient 报分位号，单信号图只报桶名，多信号才需要信号名区分
BUCKET_LABEL = "Decile {bucket}"
SIGNAL_BUCKET_LABEL = "{signal} D{bucket}"  # gradient + 多信号
SOLE_SIGNAL_LABEL = "{bucket}"

# gradient 模式下色阶已被分位占满，只剩线型可用来区分信号
GRADIENT_LINESTYLES = ("-", "--", "-.", ":")


class Palette:
    def __init__(self, spec: StyleSpec) -> None:
        self.spec = spec

    # 一次性为整张图分配样式，避免同信号多桶撞色
    def assign(self, lines: Sequence[Line], mode: str = PALETTE_MODE) -> Dict[Line, Dict]:
        if str(mode).lower() == GRADIENT_MODE:
            return self._gradient(lines)
        return self._by_signal(lines)

    # 分位桶沿色阶铺开，多空腿等特殊桶用强调色加粗压在最上层。
    # 色阶按分位分配，因此多信号同图时改用线型区分信号，否则两路信号完全撞色。
    def _gradient(self, lines: Sequence[Line]) -> Dict[Line, Dict]:
        ranks = sorted({bucket_rank(b) for _, b in lines if bucket_rank(b) != float("inf")})
        colormap = mpl.colormaps[self.spec.gradient_colormap]
        low, high = self.spec.gradient_range
        shades = {
            rank: mpl.colors.to_hex(
                colormap(low if len(ranks) < 2 else low + (high - low) * i / (len(ranks) - 1))
            )
            for i, rank in enumerate(ranks)
        }
        signals = sorted({s for s, b in lines if b != REFERENCE_BUCKET})
        dashes = {
            s: GRADIENT_LINESTYLES[i % len(GRADIENT_LINESTYLES)]
            for i, s in enumerate(signals)
        }
        styles: Dict[Line, Dict] = {}
        for line in lines:
            signal, bucket = line
            rank = bucket_rank(bucket)
            dash = dashes.get(signal, "-")
            if rank in shades:
                styles[line] = {
                    "color": shades[rank],
                    "linestyle": dash,
                    "linewidth": self.spec.linewidth,
                    "zorder": 2,
                }
            elif bucket == REFERENCE_BUCKET:
                styles[line] = {**self._reference_style(), "zorder": 3}
            else:
                styles[line] = {
                    "color": self.spec.palette.get(f"{signal} {bucket}")
                    or self.spec.palette.get(bucket)
                    or self.spec.highlight_color,
                    "linestyle": dash,
                    "linewidth": self.spec.highlight_linewidth,
                    "zorder": 4,
                }
        return styles

    def _by_signal(self, lines: Sequence[Line]) -> Dict[Line, Dict]:
        per_signal = Counter(signal for signal, _ in lines)
        chosen: Dict[Line, str] = {}
        taken: List[str] = []
        for line in lines:
            color = self._explicit(line, per_signal)
            chosen[line] = color
            if color:
                taken.append(color)

        pool = [c for c in self.spec.fallback_colors if c not in taken]
        pool = pool or list(self.spec.fallback_colors) or ["#1f77b4"]
        cursor = 0
        for line, color in chosen.items():
            if color is None:
                chosen[line] = pool[cursor % len(pool)]
                cursor += 1
        return {
            line: (
                self._reference_style()
                if line[1] == REFERENCE_BUCKET
                else {"color": color, "linestyle": "-", "linewidth": self.spec.linewidth}
            )
            for line, color in chosen.items()
        }

    # 精确 key "信号 桶" 优先；信号级 key 仅在该信号只有一条线时生效
    def _explicit(self, line: Line, per_signal: Counter):
        signal, bucket = line
        color = self.spec.palette.get(f"{signal} {bucket}")
        if color is None and per_signal[signal] == 1:
            color = self.spec.palette.get(signal)
        if color is None and bucket == REFERENCE_BUCKET:
            color = self.spec.reference_color
        return color

    def _reference_style(self) -> Dict:
        return {
            "color": self.spec.reference_color,
            "linestyle": self.spec.reference_linestyle,
            "linewidth": self.spec.linewidth,
        }

    # REF 桶挂的是基准自己的名字；H-L 这类特殊桶没有分位号，模板对它无意义
    @staticmethod
    def label(signal: str, bucket: str, template: Optional[str] = None) -> str:
        if bucket == REFERENCE_BUCKET:
            return signal
        if template is None:
            return f"{signal} {bucket}"
        if bucket_rank(bucket) == float("inf"):
            # H-L 这类特殊桶没有分位号；模板带 {signal} 即多信号图，仍需信号名区分
            return f"{signal} {bucket}" if "{signal}" in template else str(bucket)
        try:
            return template.format(signal=signal, bucket=bucket)
        except (KeyError, IndexError):
            return template
