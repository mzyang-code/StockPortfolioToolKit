# 核心概念

四个模块串成单向数据流，模块之间只通过三份不可变契约交接。理解这三份契约，就理解了整个工具包的运作方式。

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
```

每个模块拥有唯一的公开入口（`run()`），因此任何一环都可以单独替换或单独驱动，而不影响其余模块。

## 两条入口，同一条流水线

参数送进流水线有两种方式。它们的差别只在「参数怎么写」，模块、契约与计算完全相同。

| | `backtest()` | 配置目录 |
|---|---|---|
| 参数形式 | 扁平关键字参数 | 四份 JSON |
| 数据来源 | DataFrame 或文件路径 | 文件路径 |
| 适合 | notebook 中的交互式分析 | 批量执行、复现归档 |
| 产出 | `BacktestResult` 对象 | `PipelineResult` + 落盘文件 |

```python
bt = spt.backtest(signals=alpha_df, prices=price_df, horizon=5)   # 门面
result = spt.run_pipeline("configs/")                              # 配置目录
```

`backtest()` 本身不含任何计算：它把扁平参数组装成 `InputConfig` / `EngineConfig` /
`AnalyzerConfig` / `VisualizerConfig`，再依次驱动同样的四个模块。两条路径因此**逐值一致**，
包括 `members`、`aligned` 这类最底层的中间产物。

`bt.to_config()` 可把门面这边的参数反向导出成四份 JSON，交给 `run_pipeline` 复跑。

!!! note "第三种方式：直接构造配置对象"

    四个 Config 都是普通 dataclass，可以用 Python 直接构造而不经过 JSON，适合预设覆盖不到
    又不想写文件的场景：

    ```python
    from stockportfoliotoolkit.config_schema import InputConfig, PriceSpec, SignalSpec

    cfg = InputConfig(prices=PriceSpec(frame=price_df),
                      signals=[SignalSpec(name="MOM", frame=alpha_df)])
    bundle = InputProcessor(cfg).run()
    ```

## 列名唯一真源

所有产物表的列名集中定义在 `contracts.py`，任何模块都不得自造字面量。

| 代码中的语义名 | 实际列名 | 含义 |
|---|---|---|
| `DATE` | `date` | 调仓日或观测日 |
| `ASSET` | `id` | 资产标识，包内统一转为字符串 |
| `SIGNAL` | `signal_model` | 信号名；基准行中取基准名 |
| `ALPHA` | `alpha` | 因子值 |
| `CLOSE` / `CAP` | `close` / `cap` | 收盘价、市值 |
| `FWD_RET` | `fwd_ret` | 前视收益 |
| `BUCKET` | `bucket` | 分位桶标签 |
| `WEIGHT` | `weight` | 加权方案标签 |
| `RET` | `ret` | 组合收益 |
| `N_NAMES` | `count` | 成分数量 |

两个特殊桶标签：多空腿为 `H-L`（可由 `engine.long_short.label` 改名），外部基准固定为 `REF`。

分位桶标签是 `"0"` 到 `"n-1"` 的**字符串**，`"0"` 为 alpha 最低的一组。排序时分位桶按数值升序，`H-L` 与 `REF` 排在最后。

---

## ① InputProcessor

职责：取数 → 标准化列名 → 建立调仓日历 → 打包成 `InputBundle`。

数据可以来自文件，也可以是内存中的 DataFrame。两者走同一条处理链路——差别只在取数那一步，
之后的列映射、dtype 归一与缺失统计完全一致。文件内置支持 `feather`、`parquet`、`csv` 三种格式。

```python
SignalSpec(name="MOM", path="${DATA}/mom.feather")   # 文件
SignalSpec(name="MOM", frame=alpha_df)               # 内存
```

`path` 与 `frame` 恰好给一个：两个都给无从判断以哪个为准，都不给则没有数据来源。
`frame` 承载的是 DataFrame，无法序列化，因此不是 JSON 可写项——配置里写 `frame` 会被拒绝。

入口处即拦截的结构性错误：

- `input.signals` 为空
- 多路信号重名
- 价格面板存在重复的 `(date, id)`——会让市值关联膨胀
- 价格面板过滤后为空
- 调仓日历为空

### 列名映射的两种模式

`column_map` 写法为 `{"包内列名": "源文件列名"}`。它整体留空与写了内容，含义不同：

| `column_map` | 行为 |
|---|---|
| 整体留空 | **自动识别**：按契约列名在源表中同名匹配，匹配不上的必需列报错 |
| 写了内容 | **显式模式**：完全以声明为准，未声明的列一律不取 |

只认「整体留空」而不逐列补全，是因为在显式模式下遗漏某列是有意义的声明：`prices` 不映射
`close` 正是「本面板无可用价格序列，只供市值与交易日历」的表达方式。逐列补全会把这个开关废掉。

源表列名已经是 `date` / `id` / `alpha` 时因此不必写映射。

### 调仓日历的构建

日历基于 `calendar.source` 指定的表（`signals` 或 `prices`）的日期集合，按 `first_rebalance` / `last_rebalance` 截断后，每 `rebalance_freq` 个交易日取一个。

!!! note "auto_stride：避免二次抽稀"

    信号若只在调仓日落盘，其日期序列的原生间隔可能已经等于或大于 `rebalance_freq`。此时再按 `freq` 抽稀会把周期数又砍掉一倍。

    `auto_stride` 默认打开：原生间隔（相邻日期在交易日历上位置差的中位数）不小于 `rebalance_freq` 时，不再二次抽稀。实际采用的步长记录在 `bundle.meta["calendar"]` 中。

### InputBundle

| 字段 | 必需列 | 说明 |
|---|---|---|
| `signals` | `date`、`id`、`signal_model`、`alpha` | 多路信号纵向堆叠；`fwd_ret` 可选 |
| `prices` | `date`、`id`、`close`、`cap` | 未映射的列整列为 NaN |
| `calendar` | — | `DatetimeIndex`，为空时报错 |
| `references` | `date`、`name`、`ret`、`frequency` | 可为 `None` |
| `meta` | — | 各信号的行数、资产数、区间、日历覆盖率与源文件缺失率 |

`meta` 中的 `source_na_rate` 报的是**源文件有多脏**，而非产出表里还剩多少 NaN——`dropna` 打开时这些行已被丢弃。

---

## ② PortfolioEngine

职责：对齐 alpha 与前视收益 → 截面分桶 → 按加权方案折算组合收益。

处理链路：

1. 只保留落在调仓日历上的信号记录
2. 按 `forward_return.source` 取得 `fwd_ret`（价格口径或信号自带）
3. 关联市值，丢弃 `alpha` 或 `fwd_ret` 缺失的行
4. 每个 (调仓日, 信号) 截面内按 alpha 等频分桶
5. 逐 (日, 信号, 桶) 对每个加权方案计算 `Σ wᵢ·retᵢ`
6. 追加多空腿与外部基准行

详细字段说明见 [engine.json 参考](../reference/config-engine.md)。

### EngineResult

| 字段 | 列 | 说明 |
|---|---|---|
| `returns` | `date`、`signal_model`、`bucket`、`weight`、`ret`、`count` | 逐期组合收益长表 |
| `members` | `date`、`signal_model`、`id`、`bucket` | 每期各桶的成分明细，换手率由它计算 |
| `aligned` | `date`、`id`、`signal_model`、`alpha`、`fwd_ret`、`cap` | 分桶前的对齐面板，IC 由它计算 |

采用长表而非宽表，因此任意数量的加权方案都能装进同一张表，新增方案不改变表结构。

---

## ③ Analyzer

职责：把组合收益折算成指标、净值曲线与诊断序列。

### 年化因子

每年期数按以下优先级确定：

1. `analyzer.periods_per_year` 显式给出时直接采用
2. 否则由 `trading_days_per_year / engine.holding_days` 推导（默认 `252 / holding_days`）

### AnalysisResult

| 字段 | 粒度 | 内容 |
|---|---|---|
| `summary` | `(signal_model, bucket, weight)` | `n_periods` + 配置的指标 + `turnover` + `ic_mean` |
| `curves` | `(date, signal_model, bucket, weight)` | `equity` 与 `cum_log_ret` |
| `turnover` | `(signal_model, bucket, date)` | 逐期换手率 |
| `ic` | `(signal_model, date)` | 逐期信息系数与有效样本数 |

`summary` 的行数为 `信号数 × (分位数 + H-L + 基准数) × 加权方案数`。

!!! note "vol_rescale 是整体替换，不是并列输出"

    打开 `analyzer.vol_rescale` 后，收益序列整体替换为缩放到目标波动的版本，`summary` 与 `curves` 均基于缩放后的序列。工具包不会同时给出缩放前后两套口径。

    缩放系数是全样本单一常数，因此不改变曲线形状，也不改变夏普比率。

---

## ④ Visualizer

职责：把 `AnalysisResult` 渲染成 PNG 与 CSV。

图表的完整配置有五十余个字段，其中绝大多数是样式。实际决定「画什么」的只有 `buckets` 与
`color_mode` 两项，因此常用组合收敛成了两个预设名：

| 预设 | 等价配置 | 用途 |
|---|---|---|
| `long_short` | `buckets=["H-L","REF"]`、`color_mode="palette"` | 多空腿与基准对比 |
| `deciles` | 分位桶 + `H-L`、`color_mode="gradient"` | 拆解单一策略的分位结构 |

```python
bt.plot("long_short")      # 返回 matplotlib Figure
bt.save("outputs/")        # 两个预设各出一张
```

`deciles` 的桶列表按 `n_buckets` 动态生成。手写配置时这串 `"0".."9"` 与 `engine.n_buckets`
分处两个文件，改一处而忘了另一处，图与数据就对不上。

样式本身不进预设也不进函数签名，集中在全局 `settings`：

```python
spt.settings.style.figsize = (10, 6)
spt.settings.style.palette = {"MOM": "#1f77b4"}
spt.settings.reset()
```

配置中显式写了 `style` 时以配置为准，不受全局影响；留空则渲染时取 `settings.style`，
因此全局改动对已构造好的配置同样生效。

图表先按**加权方案**切分，再按图表类型决定多路信号怎么放：

| | 策略对比图（`color_mode: palette`） | 分位图（`color_mode: gradient`） |
|---|---|---|
| 多信号 | 叠在同一张，按信号分配颜色 | 每路信号单独一张 |
| 文件名 | `{name}_{weight}.png` | `{name}_{signal}_{weight}.png` |

判定由 `color_mode` 自动完成：分位图的色阶正是按分位铺开的，再塞进第二路信号既撞色又撞图例。该行为可由 `charts[].split_by_signal` 显式覆盖。

!!! info "市场基准来自配置，不来自包内"

    包内不附带市场指数数据。基准在 `input.references` 中声明，以 `REF` 桶进入曲线表，再把 `"REF"` 列入该图的 `buckets` 即可上图。线条样式走 `style.reference_color` 与 `style.reference_linestyle`。

---

## 扩展点

每个阶段暴露一个注册表。注册自定义类后按名字引用即可，无需修改包内代码。

| 注册表 | 基类 | 引用位置 | 内置项 |
|---|---|---|---|
| `ALPHA_SOURCES` / `PRICE_SOURCES` / `REFERENCE_SOURCES` | `AlphaSource` 等 | `format` | `feather`、`parquet`、`csv`、`frame` |
| `WEIGHTERS` | `Weighter` | `engine.weights` / `weights=` | `ew`、`vw` |
| `METRICS` | `Metric` | `analyzer.metrics` / `metrics=` | `ann_ret`、`ann_vol`、`sharpe`、`max_drawdown`、`total_equity`、`hit_rate` |
| `CHARTS` | `Chart` | `charts[].type` | `cumulative_log_return` |
| `TABLES` | `Table` | `tables[].type` | `summary`、`ic`、`turnover` |

`frame` 是内存 DataFrame 的实现键，由 `spec.frame is not None` 自动选中，不需要也不应该写进
`format`。

```python
from stockportfoliotoolkit.engine import WEIGHTERS, Weighter

@WEIGHTERS.register()
class InverseVolWeighter(Weighter):
    name = "inverse_vol"          # 结果表里显示为 INVERSE_VOL

    def weights(self, frame):
        w = 1.0 / frame["cap"].to_numpy()
        return w / w.sum()
```

注册名不区分大小写，重复注册同名项会报错。结果表中的加权方案标签默认取注册名的大写形式。

---

## 严格校验

四份配置由 dataclass 定义，加载时逐项严格校验：未知键直接拒绝并列出可用项。

```
ConfigError: engine: 未知配置项 ['n_bucket']；可用项为 ['forward_return', 'holding_days', ...]
```

`backtest()` 是普通 Python 函数，拼错参数名同样在调用处报 `TypeError`：

```
TypeError: backtest() got an unexpected keyword argument 'n_bucket'
```

两条路径都不接受静默忽略。这条规则在回测里尤其要紧——被忽略的参数会让程序退回默认值，
照样算出一条看起来完全正常的净值曲线，没有任何迹象提示结果用的不是你写的参数。

## 按数据推导的默认值

`backtest()` 有三处默认值不是固定常数，而是看数据定的。它们各自对应一类容易算错又不报错的情形。

| 参数 | 缺省行为 | 不这样做会怎样 |
|---|---|---|
| `rebalance_freq` | 取 `horizon` | 两者不等时相邻持有窗口重叠或留空仓缺口，净值与回撤失真 |
| `weights` | 价格面板有 `cap` 才加 `vw` | 无市值数据时市值加权产出整列 NaN，不报错 |
| `forward_return.source` | 信号自带 `fwd_ret` 则取 `signals` | 取 `close` 会静默丢弃那一列算好的收益 |

三者都可以显式覆盖，且覆盖后原有告警照常发出——自动缺省只是把正确口径设成默认，
不掩盖有意为之的差异。详见 [Python API 参考](../reference/api.md)。
