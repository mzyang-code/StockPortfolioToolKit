# 数学口径

以下规则在全包范围内成立。本页给出每个数字的确切算法，用于核对口径而非推导理论。

通用记号：

| 记号 | 含义 |
|---|---|
| $r_1, \dots, r_n$ | 一维简单收益序列，即逐期组合收益；NaN 在进入指标前已剔除 |
| $n$ | 期数 |
| $P$ | 每年期数（`analyzer.periods_per_year`） |
| $h$ | 一期的长度（`engine.forward_return.horizon`） |
| $\bar r$ | 序列均值 $\frac{1}{n}\sum_{t=1}^{n} r_t$ |

## 收益口径

!!! danger "截面加权只用简单收益"

    组合收益为 $\sum_i w_i r_i$，其中 $r_i$ 是简单收益。**绝不在截面上平均对数收益**——对数收益的
    加权平均不等于组合的对数收益，跨资产平均会引入系统性偏差。

    对数刻度只是可视化层的选择，不影响任何指标的计算。

### 实现收益

取价格口径（`forward_return.source = "prices"`）时，逐资产计算纯价格收益：

$$
\mathrm{fwdret}_{i,t} = \frac{\mathrm{close}_{i,\,t+h}}{\mathrm{close}_{i,t}} - 1
$$

该口径与 alpha 自身的预测期解耦——因子预测多久是因子的事，收益测多长单独声明。取信号口径
（`= "signals"`）时直接使用信号自带的 `fwd_ret` 列，工具包不做任何再加工。

### 一期有多长

$h$ 是全包唯一一处定义「一期有多长」的地方，为必填项。三处同时以它为准：前视收益的测量窗口、
日频基准的复利窗口、`holding_days` 未给出时的继承值。

它的**单位**则由 `input.frequency` 决定：日度口径下数交易日，月度口径下数自然月。月度口径的
`close` 取各月最后一个可用收盘价，因此上式中的 $t$ 与 $t+h$ 指的是两个月份的月末，而不是面板上
相隔 $h$ 行的两条记录。

`engine.holding_days` 仅用于年化折算，不改变任何一期收益的测量方式。两者显式不等时发出
`HoldingPeriodWarning`。

!!! warning "调仓间隔应与测量期相等"

    `input.calendar.rebalance_freq` 与 $h$ 不等时，相邻两期的持有窗口会重叠或留下空仓缺口：

    - 间隔 < 测量期：窗口互相重叠，逐期累乘会把同一段行情重复计入
    - 间隔 > 测量期：期间存在空仓缺口

    两种情况下由累乘得到的 `total_equity` 与 `max_drawdown` 均失真。引擎就此告警但不拦截，
    因为重叠窗口下的信息系数仍有分析价值。

---

## 年化因子

$P$ 显式给出时直接采用，否则由持有期推导：

$$
P = \frac{B}{\mathrm{holdingdays}}, \qquad
B = \begin{cases}
\text{`analyzer.trading\_days\_per\_year`（默认 252）} & \text{`frequency` = daily} \\
12 & \text{`frequency` = monthly}
\end{cases}
$$

月频面板沿用默认的日度口径会让 $P$ 偏离 21 倍，且不触发告警。

---

## 指标

`summary` 表中每一行是一个 `(signal_model, bucket, weight)` 组合，以下各式作用于该行对应的收益序列。

### ann_ret —— 年化收益

$$
\mathrm{AnnRet} = \bar r \cdot P = \frac{P}{n}\sum_{t=1}^{n} r_t
$$

!!! note "算术年化，不是复合年化"

    该指标是逐期收益的算术平均乘以每年期数，**不是** $E_n^{P/n} - 1$。后者是单独的指标
    [`cagr`](#cagr--复合年化收益)。

    两者可以相差很多，方向由 $P$ 与波动共同决定：复利的凸性把结果往上推
    （$(1+\bar r)^P - 1 > \bar r P$），波动拖累把它往下拉（约 $\sigma^2/2$）。月频面板
    （$P = 12$）上凸性通常占上风，`cagr` 明显高于 `ann_ret`；日频面板（$P = 252$）上单期收益
    极小，两者接近，波动大时 `cagr` 反而更低。

    同一张 `summary` 里 `ann_ret` 走算术口径、`total_equity` 与 `cagr` 走几何累乘，
    **不可互相反推**。对照外部文献的绩效表前先确认对方报的是哪一种：不少论文的 Ann. Ret. 是
    `cagr` 口径，而 Sharpe 仍按算术口径算，因此表内 $\mathrm{SR} \neq \mathrm{AnnRet} / \mathrm{AnnVol}$。

### cagr —— 复合年化收益

$$
\mathrm{CAGR} = \left(\prod_{t=1}^{n}(1 + r_t)\right)^{\frac{P}{n}} - 1
$$

净值按简单收益逐期累乘后折回年度复合增长率，与 `total_equity` 同一套口径，只是换算成年率。
期末净值跌破 0 时无定义，返回 NaN。

该指标假设每期收益首尾相接、盈亏滚动再投入，因此只在 `rebalance_freq` 与 $h$ 相等时有意义；
两者不等会触发 `HoldingPeriodWarning`，此时 `cagr` 与 `total_equity`、`max_drawdown` 一同失真。

### ann_vol —— 年化波动

$$
\mathrm{AnnVol} = \sqrt{P} \cdot \sqrt{\frac{1}{n-1}\sum_{t=1}^{n}\left(r_t - \bar r\right)^2}
$$

样本标准差（$\mathrm{ddof} = 1$）。序列长度小于 2 时返回 NaN。

### sharpe —— 夏普比率

$$
\mathrm{SR} = \frac{\mathrm{AnnRet} - r_f}{\mathrm{AnnVol}}
$$

$r_f$（`analyzer.risk_free_rate`）直接作用于**年化**收益，因此应填年化无风险利率。`ann_vol`
非有限或不为正时返回 NaN。

### max_drawdown —— 最大回撤

$$
E_t = \prod_{s=1}^{t}(1 + r_s), \qquad
\mathrm{MDD} = \min_{1 \le t \le n} \left( \frac{E_t}{\max_{s \le t} E_s} - 1 \right)
$$

取值为负数或 0，即全程最低点相对此前峰值的跌幅。

### total_equity —— 期末净值

$$
E_n = \prod_{t=1}^{n}(1 + r_t)
$$

起点为 1.0 的净值终值，几何累乘口径。

### n_periods —— 期数

$$
n = \#\{t : r_t \text{ 非 NaN}\}
$$

该行实际参与指标计算的期数。某个桶在部分期上成分不足 `min_names` 时，其 $n$ 会小于调仓日历长度。

---

## 曲线

$$
\mathrm{equity}_t = \prod_{s=1}^{t}(1 + r_s), \qquad
\mathrm{cumlogret}_t = \sum_{s=1}^{t}\ln(1 + r_s)
$$

两条曲线并列存在于 `curves` 表中，图表按类型选用其一。对数刻度是可视化选择，不构成另一套收益口径。

### 裁剪与原点

进入曲线计算前，收益按 `analyzer.curves.clip_lower`（默认 $-0.99$）做下限裁剪：

$$
\tilde r_t = \max(r_t,\ \mathrm{cliplower})
$$

防止单期 −100% 以下的异常值把净值打到 0 或负数后再也无法恢复。该裁剪**只作用于曲线**，不影响
`summary` 中的指标。

每条曲线前置一个零点（$\mathrm{equity} = 1$、$\mathrm{cumlogret} = 0$），横坐标取最早一期的前一个
工作日。`analyzer.curves.shared_origin` 打开时（默认）所有曲线共用同一原点，使不同起始期的序列
在图上可比。

---

## 诊断

### turnover —— 换手率

相邻两期成分集合 $S_t$ 与 $S_{t-1}$ 的 Jaccard 距离：

$$
\mathrm{turnover}_t = 1 - \frac{\left|S_t \cap S_{t-1}\right|}{\left|S_t \cup S_{t-1}\right|}
$$

多空的成分取多头端与空头端的**并集**后再算。首期无前一期可比，记 NaN。`summary` 中的
`turnover` 是逐期值的算术平均。

该定义衡量的是成分名单的变动比例，与权重变化无关——等权与市值加权在同一分位桶上得到相同的换手率。

### ic_mean —— 信息系数

每期截面内 alpha 与实现收益的 Spearman 相关，即两者秩的 Pearson 相关：

$$
\mathrm{ic}_t = \mathrm{corr}\left(\mathrm{rank}(\alpha_t),\ \mathrm{rank}(\mathrm{fwdret}_t)\right)
$$

$$
\mathrm{icmean} = \frac{1}{\left|T\right|}\sum_{t \in T} \mathrm{ic}_t,
\qquad T = \{t : \mathrm{ic}_t \text{ 非 NaN}\}
$$

截面有效样本数低于 `analyzer.diagnostics.ic_min_names`（默认 20）时该期记 NaN。`ic_mean` 按信号
分组，与桶和加权方案无关——因此同一信号的所有行共享同一个 `ic_mean`。

---

## 波动率缩放

`analyzer.vol_rescale` 打开后，每条收益序列乘以一个常数，使其全样本波动率对齐目标序列：

$$
c = \frac{\sigma\left(r^{\mathrm{ref}}\right)}{\sigma(r)}, \qquad r^{\mathrm{scaled}}_t = c \cdot r_t
$$

三条性质：

- 缩放系数是**全样本单一常数**，不随时间变化，因此不改变曲线形状
- 不改变夏普比率——分子分母同比例缩放
- 目标序列自身不缩放（$c = 1$）

有效样本数低于 `min_periods`（默认 20）时该序列的标准差记 NaN，此时系数退化为 1，即不缩放。

!!! note "整体替换，不是并列输出"

    打开该开关后，`summary` 与 `curves` 全部基于缩放后的序列。工具包不会同时给出缩放前后两套口径。

---

## 加权

每期每桶的组合收益为成分收益的加权和：

$$
r_t = \sum_{i \in S_t} w_i \cdot \mathrm{fwdret}_{i,t}, \qquad \sum_{i \in S_t} w_i = 1
$$

### 等权

$$
w_i = \frac{1}{\left|S_t\right|}
$$

桶内成分数为 0 时该桶收益记 NaN。

### 市值加权

$$
w_i = \frac{\max(\mathrm{cap}_i,\ 0)}{\sum_{j \in S_t} \max(\mathrm{cap}_j,\ 0)}
$$

缺市值或市值非正的成分权重记 0，等价于剔除后重新归一。

!!! note "为何裁掉非正市值"

    不裁负值会让分母变小甚至跨零，权重随之出现杠杆与反向暴露。市值合计不为正时该桶收益记 NaN。

---

## 基准

基准一律由使用者声明（配置中的 `input.references`，`backtest()` 的 `references=` 参数），包内不
附带市场指数数据，也不存在绕过声明直接绘制的基准曲线。

`frequency = "daily"` 的序列按日收益 $\rho_u$ 在持有窗口上复利，$a_t$ 为第 $t$ 期的调仓锚点，
$\ell$ 为 `reference_lag`：

$$
r^{\mathrm{REF}}_t = \prod_{u \,\in\, [\,a_t + \ell,\ a_t + \ell + h\,)} (1 + \rho_u) - 1
$$

窗口长度取 $h$ 而非 `holding_days`——基准与组合必须测同一个窗口才可比。`frequency = "period"`
的序列已是周期收益，直接按调仓日历对齐。

月度口径（`input.frequency = "monthly"`）下窗口两端都取自然月末——起点为锚点所在月的月末，末端
为其后第 $h$ 个月的月末，$\ell = 1$ 时为左开右闭、$\ell = 0$ 时为左闭右开；`period` 序列按自然月
对齐。组合那一期测的是月末收盘到月末收盘，逐日推算会在两端各错一截。

因此基准与组合走同一套周期化口径：`rebalance_freq` 与 $h$ 不等时，基准同样受重叠持有期或空仓
缺口影响，不是一条独立于调仓节奏的买入持有曲线。

一条 `references` 会对每个加权方案各复制一行，因此 `summary` 中同一基准在 EW 与 VW 两行上取值
相同——基准序列本身与组合的加权方案无关。
