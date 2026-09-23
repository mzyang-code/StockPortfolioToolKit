---
hide:
  - toc
---

<div class="alpholio-hero" markdown>

# alpholio { .alpholio-hero__title }

配置驱动的截面投资组合回测工具包。输入端只需提供 alpha，分桶、加权、指标计算与出图由工具包完成。
{ .alpholio-hero__tagline }

[快速开始](guide/quickstart.md){ .alpholio-btn .alpholio-btn--primary }
[GitHub](https://github.com/mzyang-code/alpholio){ .alpholio-btn .alpholio-btn--ghost }
{ .alpholio-hero__actions }

</div>

## 从这里开始

<div class="grid cards" markdown>

-   :material-rocket-launch-outline: **快速开始**

    ---

    安装、月频与日频两个完整例子，以及全部图表

    [:octicons-arrow-right-24: 照着跑一遍](guide/quickstart.md)

-   :material-sitemap-outline: **核心概念**

    ---

    四个模块、三份契约与扩展点

    [:octicons-arrow-right-24: 运作方式](guide/concepts.md)

-   :material-file-document-multiple-outline: **产物与落盘**

    ---

    图与表的命名规则、落点与完整长表导出

    [:octicons-arrow-right-24: 看产出什么](guide/outputs.md)

-   :material-function-variant: **数学口径**

    ---

    每个指标的确切算法与失真条件

    [:octicons-arrow-right-24: 核对公式](guide/math.md)

-   :material-language-python: **Python API**

    ---

    `backtest()` 逐参数说明与结果对象

    [:octicons-arrow-right-24: API 参考](reference/api.md)

</div>

## 职责边界

| 工具包负责 | 工具包不负责 |
|---|---|
| 截面分桶、多空构建 | 生成 alpha 信号 |
| 等权 / 市值加权及自定义加权 | 提供行情数据 |
| 年化收益、波动、夏普、回撤、换手、IC | 撮合、滑点与交易成本建模 |
| 净值曲线与指标表落盘 | 实盘下单 |

## 设计约定

三条贯穿全包、且有测试覆盖的口径约定：

!!! note "截面加权只用简单收益"

    绝不在截面上平均对数收益。对数刻度仅是可视化层的选择。

!!! note "`forward_return.horizon` 是唯一的「一期有多长」"

    `engine.holding_days` 留空即继承该值。两者显式不等时告警但不中断，因为那意味着收益的测量期与年化时假定的持有期不是同一件事。

    一期的**单位**则由 `input.frequency` 单独声明：日度数交易日、月度数自然月，年化基数随之取 252 或 12。月频面板漏声明会让年化指标偏离 21 倍且不告警，写法见[月频面板](guide/quickstart.md#月频三路-alpha-同跑)。

!!! warning "调仓间隔应与测量期相等"

    `input.calendar.rebalance_freq` 与 `horizon` 不等时，相邻两期的持有窗口会重叠或留下空仓缺口，逐期累乘出的净值与最大回撤会失真。引擎就此发出告警。

## 基准

基准序列由使用者自备，在 `input.references` 中声明后进入结果表与图表，`bucket` 固定为 `REF`。包内不附带任何市场指数数据。

等权组合应配等权指数、市值加权组合应配市值加权指数——同口径才谈得上比较。两套加权各配一条指数的完整配置见[日频例子](guide/quickstart.md#日频单路-alpha-配两条基准)。

## 许可证

MIT
