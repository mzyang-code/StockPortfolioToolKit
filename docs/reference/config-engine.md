# engine.json

Portfolio Engine 的配置。职责是把标准化后的面板切成分位桶、按加权方案折算成组合收益，并产出多空腿与基准行。

对应 `EngineConfig`，可由 `EngineConfig.from_file("configs/engine.json")` 单独加载，也可以用 Python 直接构造。
走 `backtest()` 时这些字段由函数参数组装，对应关系见 [Python API 参考](api.md)。

## 字段总览

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `forward_return.horizon` | `int` | **必填** | 前视收益的测量期长度，单位随 `input.frequency` |
| `forward_return.source` | `str` | `"prices"` | 前视收益来源，取 `prices` 或 `signals` |
| `forward_return.clip_lower` | `float \| null` | `null` | 前视收益的下限裁剪阈值 |
| `n_buckets` | `int` | `10` | 分位桶数量，必须 ≥ 2 |
| `min_names` | `int` | `20` | 单个截面进入分桶所需的最少有效样本数 |
| `holding_days` | `int \| null` | `null` | 年化折算所用的持有期数，留空继承 `horizon` |
| `weights` | `list[str]` | `["ew", "vw"]` | 加权方案名，取自 `WEIGHTERS` 注册表 |
| `weight_options` | `dict` | `{}` | 按方案名传给加权器构造函数的额外参数 |
| `include_references` | `bool` | `true` | 是否将外部基准纳入结果表 |
| `reference_lag` | `int` | `1` | 日频基准复利窗口相对锚点的偏移 |
| `long_short.enabled` | `bool` | `true` | 是否构建多空腿 |
| `long_short.label` | `str` | `"H-L"` | 多空腿在结果表 `bucket` 列中的取值 |
| `long_short.reverse` | `bool` | `false` | 反向多空，即低分位减高分位 |

未列出的键会被拒绝：严格校验会报出未知项并附上可用项清单。

---

## forward_return

前视收益口径。这是全包唯一一处定义「一期有多长」的地方。

### horizon

:material-alert-circle: **必填**，`int`，需 ≥ 1。

每期实现收益跨越的期数。**单位随 [`input.frequency`](config-input.md#frequency)**：日度口径下数交易日，月度口径下数自然月。三处行为同时以它为准：

- 取价格口径时，逐资产计算 `close[t+h] / close[t] - 1`（月度口径下 `t` 与 `t+h` 取各自月份的最后一个可用收盘价）
- 日频外部基准在长度为 `h` 的窗口上复利，与组合同窗口才可比
- `holding_days` 未单独指定时继承该值

缺失或小于 1 时直接抛 `ConfigError`，不会拖到下游才失败。

### source

`str`，默认 `"prices"`。

!!! note "`backtest()` 的默认值不同"

    配置这边固定默认 `"prices"`；`backtest()` 则按数据推导——信号提供 `fwd_ret` 时取
    `"signals"`，否则取 `"prices"`。

    差别在于两者掌握的信息量不同：写配置的人知道自己的数据长什么样，而 `backtest()`
    要在看过数据之后才能定。自带列优先于 `close`，是因为前者是专门算过一遍实现收益的结果，
    后者往往只是价格面板顺带提供的。

=== "prices"

    逐资产按 `close` 推算前视收益，纯价格口径，与 alpha 自身的预测期解耦。

    要求价格面板提供 `close`。未映射该列时抛 `ConfigError`，错误信息直接指回配置本身，而非让下游报出「没有任何调仓日通过分桶」这类指不回原因的消息。

    信号文件若同时映射了 `fwd_ret`，该列被丢弃并发出 `IgnoredForwardReturnWarning`——配置既已指定价格口径，就以价格为准。

=== "signals"

    直接取信号文件自带的 `fwd_ret` 列。适用于只有预测结果、没有价格序列的输入文件。

    此时价格面板只承担关联市值与定义交易日历两件事，`column_map` 中可以不写 `close`。

    信号的 `column_map` 未映射 `fwd_ret` 时抛 `ConfigError`。

其他取值抛 `ConfigError`。

### clip_lower

`float | null`，默认 `null`。

对前视收益做下限裁剪。常用取值 `-1.0`，用于防止数据异常产生的低于 −100% 的收益。留空则不裁剪。

---

## 分桶

### n_buckets

`int`，默认 `10`，必须 ≥ 2。

在每个 (调仓日, 信号) 截面内按 alpha 等频分桶，桶标签为 `"0"` 至 `"n-1"` 的字符串，`"0"` 为 alpha 最低的一组。小于 2 时抛 `ContractError`。

### min_names

`int`，默认 `20`。

单个截面内 alpha 非空的样本数低于该值时，整个截面作废，不产出任何桶。分位数因取值重复而退化时同样整日作废。

所有调仓日均未通过分桶时抛 `ContractError`，并在消息中回显当前的 `min_names` 与 `n_buckets`。

### long_short

分位桶两端相减得到的多空组合。

| 子字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | `bool` | `true` | 关闭后结果表中不含多空腿 |
| `label` | `str` | `"H-L"` | 该腿在 `bucket` 列中的取值 |
| `reverse` | `bool` | `false` | `false` 为高桶减低桶，`true` 为低桶减高桶 |

多空腿按 (日, 信号, 加权方案) 对齐相减，`count` 列取两端成分数之和。任一端缺失时该腿为空。

---

## 加权

### weights

`list[str]`，默认 `["ew", "vw"]`。

加权方案名，取自 `WEIGHTERS` 注册表。内置两项：

| 名称 | 结果表标签 | 行为 |
|---|---|---|
| `ew` | `EW` | 等权。桶内成分数为 0 时该桶收益记 NaN |
| `vw` | `VW` | 市值加权。缺市值或市值非正的成分权重记 0，等价于剔除后重新归一；市值合计不为正时该桶收益记 NaN |

!!! note "市值非正的成分为何裁到 0"

    不裁负值会让市值合计变小甚至跨零，权重随之出现杠杆与反向暴露。

列表为空时抛 `ContractError`。两个方案产出相同标签时同样抛 `ContractError`——结果表以标签区分加权方案，重复会导致行无法分辨。

自定义加权器注册后即可在此按名引用。

### weight_options

`dict`，默认 `{}`。

按方案名索引，值作为关键字参数传入对应加权器的构造函数，在加权器内部通过 `self.options` 访问。内置的 `ew` 与 `vw` 不读取任何选项。

```json
{
  "weights": ["ew", "inverse_vol"],
  "weight_options": {
    "inverse_vol": { "lookback": 60 }
  }
}
```

---

## 基准

### include_references

`bool`，默认 `true`。

是否把 `input.references` 中声明的基准折算后纳入结果表。基准行的 `bucket` 固定为 `"REF"`，`signal_model` 取基准名，`count` 记 0，并对每个加权方案各复制一行，便于下游统一过滤。

!!! warning "一条 references 会覆盖全部加权方案"

    逐加权方案复制意味着一条基准会同时出现在 EW 与 VW 两套结果中。等权与市值加权各配一条指数时，需在图表层按 `weights` 与 `signals` 分别限定，见[给两套加权各配一条基准](../guide/multi-signal.md#给两套加权各配一条基准)。

### reference_lag

`int`，默认 `1`。

日频基准的复利窗口相对锚点的偏移。

=== "日度口径"

    窗口取 `[锚点 + lag, 锚点 + lag + horizon)`，即 `horizon` 个交易日：

    - `1`：次日起算，与持仓建立的时点对齐
    - `0`：当日起算

    窗口内数据不足 `horizon` 天的锚点被跳过。

=== "月度口径"

    窗口末端取「锚点所在月 + `horizon` 个月」的**自然月末**，而不是「锚点日期 + `horizon` 个月」那一天：

    - `1`：`(锚点, 末端]`，次日起算
    - `0`：`[锚点, 末端)`，当日起算

    锚点通常落在月内最后一个交易日（如 3 月 29 日），逐日加一个月会得到 4 月 29 日，把 4 月最后一两天的行情漏在窗口外；而组合那一期测的是 3 月末收盘到 4 月末收盘。取自然月末才是同一个窗口。

    该口径下只区分「含锚点当日」与「次日起算」两种情形，取值须为 `0` 或 `1`；其他取值抛 `ContractError`，不会被悄悄当成 `1` 处理。基准数据未覆盖到窗口末端的锚点被跳过——月末恰为周末时，末期基准会因此缺一期。

窗口长度取 `horizon` 而非 `holding_days`，因为基准与组合必须测同一个窗口才可比。

`references[].frequency` 为 `period` 的基准已是周期收益，直接按调仓日历对齐，不受该字段影响。

---

## holding_days

`int | null`，默认 `null`，留空即继承 `forward_return.horizon`。单位与 `horizon` 相同，随 `input.frequency` 变（日度=交易日，月度=自然月）——名字里的 days 是历史沿用，月度口径下它数的是月。

仅用于年化折算：每年期数按 `年化基数 / holding_days` 计，基数在日度口径下取 `analyzer.trading_days_per_year`（默认 252），月度口径下取 12。它不改变任何一期实现收益的测量方式——那由 `horizon` 单独决定。

显式给出且与 `horizon` 不等时发出 `HoldingPeriodWarning`，可算但不中断：

```
engine.holding_days=10 与 engine.forward_return.horizon=5 不一致：
每期实现收益按 5 期测量（基准同窗口口径），
而年化因子按每年「年化基数/10」期折算。
```

两者不等意味着组合收益的测量期与声称的持有期不是同一件事，年化收益、波动与夏普会相应偏移。

---

## 告警一览

引擎在这些情形下发出告警而不中断执行：

| 告警类型 | 触发条件 | 含义 |
|---|---|---|
| `HoldingPeriodWarning` | `holding_days` ≠ `horizon` | 年化口径与测量期不是同一件事 |
| `HoldingPeriodWarning` | 调仓间隔 ≠ `horizon` | 相邻两期持有窗口重叠或存在空仓缺口 |
| `IgnoredForwardReturnWarning` | `source="prices"` 且信号带 `fwd_ret` | 自带列已丢弃，实际取价格口径 |
| `DegeneratePriceWarning` | `close` 逐资产恒定 | 前视收益恒为 0，通常是占位列被当成真实价格 |

!!! danger "调仓间隔与测量期不等会让净值失真"

    调仓间隔小于 `horizon` 时窗口互相重叠，逐期累乘会把同一段行情重复计入；大于 `horizon` 时期间存在空仓缺口。两种情况下 `total_equity` 与 `max_drawdown` 均不可信。

    通常应让 `input.calendar.rebalance_freq` 与 `horizon` 相等。该组合只告警不拦截，因为重叠窗口下的信息系数仍有分析价值。

---

## 完整示例

```json
{
  "n_buckets": 10,
  "min_names": 20,
  "weights": ["ew", "vw"],
  "weight_options": {},
  "include_references": true,
  "reference_lag": 1,
  "long_short": {
    "enabled": true,
    "label": "H-L",
    "reverse": false
  },
  "forward_return": {
    "horizon": 5,
    "source": "prices",
    "clip_lower": null
  }
}
```

## 产出

引擎的唯一出口是 `EngineResult`：

| 字段 | 列 | 内容 |
|---|---|---|
| `returns` | `date`、`signal_model`、`bucket`、`weight`、`ret`、`count` | 逐期组合收益长表 |
| `members` | `date`、`signal_model`、`id`、`bucket` | 每期各桶的成分明细 |
| `aligned` | `date`、`id`、`signal_model`、`alpha`、`fwd_ret`、`cap` | 分桶前的对齐面板 |
| `meta` | — | 桶数、加权标签、期数、多空两端标签等运行摘要 |
