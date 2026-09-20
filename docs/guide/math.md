# 数学口径

以下规则在全包范围内成立，并有测试覆盖。本页给出每个数字的确切算法，用于核对口径而非推导理论。

记号：`r` 为一维简单收益序列（逐期组合收益），`P` 为每年期数（`periods_per_year`）。

## 收益口径

!!! danger "截面加权只用简单收益"

    组合收益为 `Σ wᵢ·retᵢ`，其中 `retᵢ` 是简单收益。**绝不在截面上平均对数收益**——对数收益的加权平均不等于组合的对数收益，跨资产平均会引入系统性偏差。

    对数刻度只是可视化层的选择，不影响任何指标的计算。

### 实现收益

取价格口径时，逐资产计算纯价格收益：

```
fwd_ret[t] = close[t + h] / close[t] - 1
```

其中 `h = engine.forward_return.horizon`。该口径与 alpha 自身的预测期解耦——因子预测多久是因子的事，收益测多长由配置单独声明。

取信号口径（`source="signals"`）时直接使用信号文件自带的 `fwd_ret` 列，工具包不做任何再加工。

### 一期有多长

`engine.forward_return.horizon` 是全包唯一一处定义「一期有多长」的地方，为必填项。三处同时以它为准：前视收益的测量窗口、日频基准的复利窗口、`holding_days` 未给出时的继承值。

`engine.holding_days` 仅用于年化折算，不改变任何一期收益的测量方式。两者显式不等时发出 `HoldingPeriodWarning`。

!!! warning "调仓间隔应与测量期相等"

    `input.calendar.rebalance_freq` 与 `horizon` 不等时，相邻两期的持有窗口会重叠或留下空仓缺口：

    - 间隔 < 测量期：窗口互相重叠，逐期累乘会把同一段行情重复计入
    - 间隔 > 测量期：期间存在空仓缺口

    两种情况下由累乘得到的 `total_equity` 与 `max_drawdown` 均失真。引擎就此告警但不拦截，因为重叠窗口下的信息系数仍有分析价值。

---

## 指标

所有指标只接受一维简单收益序列，NaN 在进入指标前已被剔除。

### 年化因子

```
P = analyzer.periods_per_year                       # 显式给出时直接采用
P = trading_days_per_year / engine.holding_days     # 否则由此推导，默认 252 / holding_days
```

### ann_ret —— 年化收益

```
ann_ret = mean(r) × P
```

!!! note "算术年化，不是几何年化"

    该指标是逐期收益的算术平均乘以每年期数，**不是** `total_equity^(P/n) - 1`。

    两者在收益波动较大时可以相差很多：算术年化高于几何年化，差额随波动增大而增大。同一张 `summary` 里 `ann_ret` 走算术口径、`total_equity` 走几何累乘，两者不可互相反推。

### ann_vol —— 年化波动

```
ann_vol = std(r, ddof=1) × √P
```

样本标准差（`ddof=1`）。序列长度小于 2 时返回 NaN。

### sharpe —— 夏普比率

```
sharpe = (ann_ret - risk_free_rate) / ann_vol
```

`risk_free_rate` 直接作用于**年化**收益，因此配置中应填年化无风险利率。`ann_vol` 非有限或不为正时返回 NaN。

### max_drawdown —— 最大回撤

```
equity = cumprod(1 + r)
max_drawdown = min(equity / cummax(equity) - 1)
```

取值为负数或 0。全程最低点相对此前峰值的跌幅。

### total_equity —— 期末净值

```
total_equity = cumprod(1 + r)[-1]
```

起点为 1.0 的净值终值，几何累乘口径。

### hit_rate —— 胜率

```
hit_rate = mean(r > 0)
```

严格大于 0 才计入，收益恰为 0 的期记作未命中。该指标不在默认 `metrics` 列表中，需显式配置。

---

## 曲线

```
equity      = cumprod(1 + r)
cum_log_ret = cumsum(log1p(r))
```

两条曲线并列存在于 `curves` 表中，图表按类型选用其一。对数刻度是可视化选择，不构成另一套收益口径。

### 裁剪与原点

进入曲线计算前，收益按 `analyzer.curves.clip_lower`（默认 `-0.99`）做下限裁剪，防止单期 −100% 以下的异常值把净值打到 0 或负数后再也无法恢复。该裁剪**只作用于曲线**，不影响 `summary` 中的指标。

每条曲线前置一个零点（`equity = 1.0`、`cum_log_ret = 0.0`），横坐标取最早一期的前一个工作日。`analyzer.curves.shared_origin` 打开时（默认）所有曲线共用同一原点，使不同起始期的序列在图上可比。

---

## 诊断

### 换手率

相邻两期成分集合的 Jaccard 距离：

```
turnover[t] = 1 - |Sₜ ∩ Sₜ₋₁| / |Sₜ ∪ Sₜ₋₁|
```

多空腿的成分取多头端与空头端的**并集**后再算。首期无前一期可比，记 NaN。

该定义衡量的是成分名单的变动比例，与权重变化无关——等权与市值加权在同一分位桶上得到相同的换手率。

### 信息系数

每期截面内 alpha 与实现收益的 Spearman 相关，即两者秩的 Pearson 相关：

```
ic[t] = corr(rank(alpha), rank(fwd_ret))
```

截面有效样本数低于 `analyzer.diagnostics.ic_min_names`（默认 20）时该期记 NaN。`summary` 中的 `ic_mean` 是逐期 IC 的算术平均，按信号分组，与桶和加权方案无关——因此同一信号的所有行共享同一个 `ic_mean`。

---

## 波动率缩放

`analyzer.vol_rescale` 打开后，每条收益序列乘以一个常数，使其全样本波动率对齐目标序列：

```
factor = std(r_reference) / std(r_own)
r_scaled = r × factor
```

三条性质：

- 缩放系数是**全样本单一常数**，不随时间变化，因此不改变曲线形状
- 不改变夏普比率——分子分母同比例缩放
- 目标序列自身不缩放

有效样本数低于 `min_periods`（默认 20）时该序列的标准差记 NaN，此时系数退化为 1.0，即不缩放。

!!! note "整体替换，不是并列输出"

    打开该开关后，`summary` 与 `curves` 全部基于缩放后的序列。工具包不会同时给出缩放前后两套口径。

---

## 加权

### 等权

```
wᵢ = 1 / n
```

桶内成分数为 0 时该桶收益记 NaN。

### 市值加权

```
wᵢ = capᵢ / Σcap
```

缺市值或市值非正的成分权重记 0，等价于剔除后重新归一。

!!! note "为何裁掉非正市值"

    不裁负值会让 `Σcap` 变小甚至跨零，权重随之出现杠杆与反向暴露。市值合计不为正时该桶收益记 NaN。

---

## 基准

基准一律来自 `input.references`，包内不附带市场指数数据，也不存在绕过配置直接绘制的基准曲线。

`frequency="daily"` 的序列在 `[锚点 + reference_lag, 锚点 + reference_lag + horizon)` 窗口上复利，窗口长度取 `horizon` 而非 `holding_days`——基准与组合必须测同一个窗口才可比。`frequency="period"` 的序列已是周期收益，直接按调仓日历对齐。

因此基准与组合走同一套周期化口径：`rebalance_freq` 与 `horizon` 不等时，基准同样受重叠持有期或空仓缺口影响，不是一条独立于调仓节奏的买入持有曲线。
