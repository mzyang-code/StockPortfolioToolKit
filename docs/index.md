---
hide:
  - toc
---

<div class="spt-hero" markdown>

# StockPortfolioToolKit { .spt-hero__title }

配置驱动的截面投资组合回测工具包。输入端只需提供 alpha，分桶、加权、指标计算与出图由工具包完成。
{ .spt-hero__tagline }

[快速开始](guide/quickstart.md){ .spt-btn .spt-btn--primary }
[GitHub](https://github.com/mzyang-code/StockPortfolioToolKit){ .spt-btn .spt-btn--ghost }
{ .spt-hero__actions }

</div>

<div class="spt-flow" markdown>

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
   input.json                     engine.json                     analyzer.json                visualizer.json
```

</div>

四个模块构成单向数据流。每个模块拥有独立的 JSON 配置和唯一的公开入口，任何一环都可以单独替换而不影响其余模块。

## 三行跑通

```bash
pip install -e .
spt run --config-dir configs/
```

或在 Python 中驱动：

```python
from stockportfoliotoolkit import run_pipeline

result = run_pipeline("configs/")
result.analysis.summary        # 按 (signal_model, bucket, weight) 的指标
result.engine.returns          # 逐期组合收益长表
result.outputs                 # 已落盘的文件清单
```

## 从这里开始

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: **快速开始**

    ---

    从安装到跑出第一张净值曲线

    [:octicons-arrow-right-24: 五分钟上手](guide/quickstart.md)

-   :material-sitemap-outline: **核心概念**

    ---

    四个模块、三份契约与扩展点

    [:octicons-arrow-right-24: 运作方式](guide/concepts.md)

-   :material-function-variant: **数学口径**

    ---

    每个指标的确切算法与失真条件

    [:octicons-arrow-right-24: 核对公式](guide/math.md)

-   :material-tune-variant: **配置参考**

    ---

    逐字段说明类型、默认值与约束

    [:octicons-arrow-right-24: input.json](reference/config-input.md)

</div>

## 职责边界

| 工具包负责 | 工具包不负责 |
|---|---|
| 截面分桶、多空腿构建 | 生成 alpha 信号 |
| 等权 / 市值加权及自定义加权 | 提供行情数据 |
| 年化收益、波动、夏普、回撤、换手、IC | 撮合、滑点与交易成本建模 |
| 净值曲线与指标表落盘 | 实盘下单 |

MOM / STR / WSTR 这类价格因子在本包中属于普通输入，与任何外部 alpha 同等对待。

## 设计约定

三条贯穿全包、且有测试覆盖的口径约定：

!!! note "截面加权只用简单收益"

    绝不在截面上平均对数收益。对数刻度仅是可视化层的选择。

!!! note "`forward_return.horizon` 是唯一的「一期有多长」"

    `engine.holding_days` 留空即继承该值。两者显式不等时告警但不中断，因为那意味着收益的测量期与年化时假定的持有期不是同一件事。

!!! warning "调仓间隔应与测量期相等"

    `input.calendar.rebalance_freq` 与 `horizon` 不等时，相邻两期的持有窗口会重叠或留下空仓缺口，逐期累乘出的净值与最大回撤会失真。引擎就此发出告警。

## 基准

基准序列由使用者自备，在 `input.references` 中声明后进入结果表与图表，`bucket` 固定为 `REF`。包内不附带任何市场指数数据。

等权组合应配等权指数、市值加权组合应配市值加权指数——同口径才谈得上比较。两套加权各配一条指数的完整配置见[给两套加权各配一条基准](guide/multi-signal.md#给两套加权各配一条基准)。

## 许可证

MIT
