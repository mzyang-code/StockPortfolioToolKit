# Python API

`backtest()` 是面向交互式分析的入口：扁平关键字参数进，可继续提问的结果对象出。它不含任何计算——
参数组装成四份配置后仍由 `InputProcessor` → `PortfolioEngine` → `Analyzer` 驱动，因此与
[配置目录路径](config-input.md)算出的结果逐值一致。

```python
import alpholio as alp

bt = alp.backtest(signals=alpha_df, prices=price_df, horizon=5)
```

## 数据参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `signals` | DataFrame / 路径 / `{名称: 表}` / `SignalSpec` | 必填 | alpha 信号。映射形式一次跑多路，键即信号名 |
| `prices` | DataFrame / 路径 / `PriceSpec` | 必填 | 价格面板，提供 `close`、`cap` 与交易日历 |
| `references` | 同上 | `None` | 外部基准序列，以 `REF` 桶进入结果 |
| `signal_columns` | dict | `None` | 源列名 → 契约列名的映射 |
| `price_columns` | dict | `None` | 同上，作用于价格面板 |
| `reference_columns` | dict | `None` | 同上，作用于基准序列 |

内存 DataFrame 与文件路径等价，可混用。文件格式由后缀推断，支持 `feather`、`parquet`、`csv`。

### 列名自动识别

`*_columns` 留空时，按契约列名（`date` / `id` / `alpha` / `close` / `cap` / `fwd_ret` / `ret`）
在源表中同名匹配。源列名与之一致的表因此不必声明映射。

自动识别只在整个映射留空时生效。一旦声明了映射就进入显式模式，此时遗漏某列是有意义的表达——
价格面板不映射 `close` 正是「本面板无可用价格序列，只供市值与交易日历」的声明方式。

对不上的列会报错并列出源表实际列名，不会静默产出空表：

```
ContractError: frame<MOM>: 缺少必需列 ['date', 'id']；源列为 ['anchor', 'sym', 'alpha']。
源列名与之不同时请用 column_map 声明映射。
```

## 口径参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `horizon` | int | **必填** | 每期实现收益的测量期长度，单位随 `frequency` |
| `frequency` | str | `"daily"` | 面板频率，取 `"daily"` 或 `"monthly"` |
| `rebalance_freq` | int | 取 `horizon` | 调仓间隔，单位随 `frequency` |
| `n_buckets` | int | `10` | 分位桶数 |
| `min_names` | int | `20` | 单期通过分桶所需的最少标的数 |
| `weights` | str / list | 按数据决定 | 加权方案，取 `"ew"` / `"vw"` |
| `long_short` | bool | `True` | 是否构建多空腿 |
| `long_short_reverse` | bool | `False` | 反向，即低分位减高分位 |
| `holding_days` | int | 取 `horizon` | 年化折算用的持有期数，单位随 `frequency` |
| `forward_return_source` | str | 按数据决定 | `"prices"` 或 `"signals"` |
| `clip_lower` | float | `None` | 前视收益下限截断 |
| `first_rebalance` | str | `None` | 首个调仓日，留空取信号起点 |
| `last_rebalance` | str | `None` | 末个调仓日 |
| `calendar_source` | str | `"signals"` | 调仓日历取自信号日期还是交易日 |
| `auto_stride` | bool | `True` | 信号日历原生已够稀疏时不再二次抽稀 |
| `reference_frequency` | str | `"daily"` | 基准序列频率，`daily` 按持有期复利 |
| `reference_lag` | int | `1` | 日频基准复利起点相对锚点的偏移 |

### frequency 决定所有期数的单位

`horizon`、`rebalance_freq`、`holding_days` 数的是期，一期有多长由 `frequency` 决定：`"daily"` 下是一个交易日，`"monthly"` 下是一个自然月。年化基数随之取 252 或 12。

```python
bt = alp.backtest(signals=alpha_df, prices=panel_df, horizon=1, frequency="monthly")
```

月频面板沿用默认的 `"daily"` 会让年化指标偏离 21 倍且不触发告警，详见[数据频率](../guide/frequency.md)。

### 三处按数据推导的默认值

**`rebalance_freq` 缺省等于 `horizon`。** 两者不等时，相邻两期的持有窗口会重叠或留下空仓缺口，
逐期累乘出的净值、`total_equity` 与 `max_drawdown` 因此失真。缺省取同值使窗口首尾相接。
显式给出不等值仍会照常告警，自动缺省不掩盖有意为之的口径差异。

**`weights` 按价格面板是否提供 `cap` 决定。** 有市值列取 `["ew", "vw"]`，没有则取 `["ew"]`。
无市值数据时仍排入市值加权会产出整列 NaN 而不报错。

**`forward_return_source` 按信号是否自带实现收益决定。** 信号提供 `fwd_ret` 时取 `"signals"`，
否则由 `close` 推算取 `"prices"`。

自带列优先于 `close`，是因为两者的明确程度不对等：`fwd_ret` 是专门算过一遍实现收益的结果，
常含分红与拆股调整；而 `close` 往往只是价格面板顺带提供的——该面板本来就要承担交易日历与
市值关联两项职责，有没有 `close` 说明不了口径意图。两种口径在含分红的数据上能差出数量级。

需要强制走价格口径时显式给出 `forward_return_source="prices"`，此时自带列被丢弃并发出
`IgnoredForwardReturnWarning`。

## 分析参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `metrics` | list | 五项基础指标 | 指标清单，可选项见[数学口径](../guide/math.md) |
| `periods_per_year` | float | 由持有期推导 | 年化因子，显式给出则优先 |
| `trading_days_per_year` | float | `252.0` | 日度口径下年化因子的分子；月度口径固定取 12 |
| `risk_free_rate` | float | `0.0` | 无风险利率 |
| `turnover` | bool | `True` | 是否计算换手 |
| `ic` | bool | `True` | 是否计算信息系数 |
| `ic_min_names` | int | `20` | 单期计算 IC 所需的最少标的数 |
| `vol_rescale_to` | str | `None` | 缩放到某个基准的波动水平 |
| `curve_clip_lower` | float | `-0.99` | 曲线单期收益下限 |
| `shared_origin` | bool | `True` | 各曲线是否统一起点 |
| `output_dir` | str | `None` | `save()` 的默认落点 |

## 结果对象

`backtest()` 返回 `BacktestResult`。中间产物原样保留，二次分析不需要重跑。

### 中间产物

| 属性 | 内容 |
|---|---|
| `returns` | 逐期组合收益长表 `[date, signal_model, bucket, weight, ret, count]` |
| `curves` | 净值与累计对数收益曲线 |
| `ic` | 逐期信息系数 |
| `turnover` | 逐期换手 |
| `members` | 逐期分桶成分明细 |
| `aligned` | alpha × 前视收益 × 市值的对齐面板 |
| `bundle` / `engine` / `analysis` | 三份原始契约产物 |
| `config` | 本次实验的完整 `PipelineConfig` |

### `summary(bucket=None, weight=None, signal=None)`

指标汇总表。不给参数即全部分位。

```python
bt.summary()                    # 全部
bt.summary(bucket="H-L")        # 只看多空腿
bt.summary(weight="EW")         # 只看等权
```

### `plot(kind="long_short", weight=None, signal=None, **overrides)`

按预设名出一张图，返回 matplotlib `Figure`。

| 预设名 | 内容 |
|---|---|
| `"long_short"` | 多空腿与外部基准同图对比，带零线 |
| `"deciles"` | 分位走色阶、多空腿单独强调；桶列表跟随 `n_buckets` |

`weight` 留空取首个加权方案。多路信号画分位图时用 `signal` 指定看哪一路，留空取首路。
其余关键字直接透传给 `ChartSpec`，用于单图临时调整：

!!! note "Jupyter 中需要 inline 后端"

    返回的 `Figure` 脱离 pyplot 全局状态直接构造，因此 notebook 里要先激活 inline 后端才会渲染：

    ```python
    %matplotlib inline
    ```

    否则单元格不显示任何内容。脚本中用 `fig.savefig(...)` 不受影响。

```python
fig = bt.plot("long_short", show_title=False, legend_loc="lower right")
fig.axes[0].set_ylabel("Cumulative log return")   # 返回的是原生 Figure，可继续调
fig.savefig("fig3.pdf", dpi=300)
```

### `save(output_dir=None, charts=..., tables=..., export_returns=True)`

图 PNG 与数据表 CSV 落盘，返回文件清单。`charts` 默认两张预设图，`tables` 默认
`summary` / `turnover` / `ic` 三张表。

内存 DataFrame 输入时没有数据文件可作落点锚，因此必须给出目录——不猜测落点，也不写进当前工作目录。

### `to_config(config_dir, data_dir=None)`

把本次实验导成四份 JSON，供 `run_pipeline` 复现或随论文归档。

内存 DataFrame 无法写进 JSON，因此内存输入时需给出 `data_dir`：表会先落盘到该目录，
再把路径写进配置。

```python
bt = alp.backtest(signals=alpha_df, prices=price_df, horizon=5, n_buckets=10)
bt.to_config("paper/configs/", data_dir="paper/data/")

# 复现时
result = alp.run_pipeline("paper/configs/")
```

## 全局样式

样式字段有五十余个，改动频率远低于口径参数，因此集中在 `settings` 而非函数签名。
改一次对之后的每次渲染生效：

```python
alp.settings.style.figsize = (10, 6)
alp.settings.style.dpi = 300
alp.settings.style.palette = {"MOM": "#1f77b4"}
alp.settings.style.gradient_colormap = "plasma"

alp.settings.reset()            # 复原到出厂默认
```

逐字段说明见 [visualizer.json 的 `style` 段](config-input.md)。配置中显式写了 `style` 时以配置为准，
不受全局影响。

## 更细的控制

预设覆盖不到的场景，四个模块仍可单独驱动，配置用 Python 直接构造：

```python
from alpholio import InputProcessor, PortfolioEngine
from alpholio.config_schema import (
    InputConfig, PriceSpec, SignalSpec, EngineConfig, ForwardReturnSpec,
)

cfg = InputConfig(
    prices=PriceSpec(frame=price_df),
    signals=[SignalSpec(name="MOM", frame=alpha_df)],
)
bundle = InputProcessor(cfg).run()
engine = PortfolioEngine(
    EngineConfig(n_buckets=10, forward_return=ForwardReturnSpec(horizon=5))
).run(bundle)
```

`SignalSpec` / `PriceSpec` / `ReferenceSpec` 的 `path` 与 `frame` 恰好给一个：两个都给无从判断
以哪个为准，都不给则没有数据来源。
