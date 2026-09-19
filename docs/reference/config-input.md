# input.json

Input Processor 的配置。职责是读取文件、把源列名映射成包内统一列名、建立调仓日历，产出 `InputBundle`。

对应 `InputConfig`，可由 `InputConfig.from_file("configs/input.json")` 单独加载。

## 字段总览

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `signals[]` | `list` | **必填，至少一项** | alpha 信号源 |
| `signals[].name` | `str` | **必填** | 信号名，出现在结果表 `signal_model` 列 |
| `signals[].path` | `str` | **必填** | 文件路径，支持 `${VAR}` |
| `signals[].column_map` | `dict` | **必填** | 至少映射 `date`、`id`、`alpha` |
| `signals[].format` | `str \| null` | `null` | 留空按后缀推断 |
| `signals[].dropna` | `bool` | `true` | 丢弃关键列缺失的行 |
| `signals[].read_kwargs` | `dict` | `{}` | 透传给底层读取函数 |
| `prices.path` | `str` | **必填** | 价格面板路径 |
| `prices.column_map` | `dict` | **必填** | 至少映射 `date`、`id` |
| `prices.format` | `str \| null` | `null` | 留空按后缀推断 |
| `prices.restrict_to_signal_assets` | `bool` | `true` | 只保留信号中出现的资产 |
| `prices.read_kwargs` | `dict` | `{}` | 透传给底层读取函数 |
| `references[]` | `list` | `[]` | 外部基准序列 |
| `references[].name` | `str` | **必填** | 基准名，在结果表中作为 `signal_model` |
| `references[].path` | `str` | **必填** | 文件路径 |
| `references[].column_map` | `dict` | **必填** | 至少映射 `date`、`ret` |
| `references[].frequency` | `str` | `"daily"` | 取 `daily` 或 `period` |
| `references[].format` | `str \| null` | `null` | 留空按后缀推断 |
| `references[].read_kwargs` | `dict` | `{}` | 透传给底层读取函数 |
| `calendar.first_rebalance` | `str \| null` | `null` | 首个调仓日，留空取信号最早日期 |
| `calendar.last_rebalance` | `str \| null` | `null` | 末个调仓日，留空不截断 |
| `calendar.rebalance_freq` | `int` | `5` | 调仓间隔，单位交易日 |
| `calendar.source` | `str` | `"signals"` | 日历基准表，取 `signals` 或 `prices` |
| `calendar.auto_stride` | `bool` | `true` | 原生间隔已够稀疏时不再二次抽稀 |
| `vars` | `dict` | `{}` | 路径变量定义 |

---

## 通用字段

以下三个字段在 `signals[]`、`prices`、`references[]` 中语义一致。

### path

文件路径，支持 `${VAR}` 形式的变量展开。取值顺序：先查配置的 `vars`，再查环境变量，两处都没有则抛 `KeyError`。路径中的 `~` 会展开为用户主目录。

```json
{
  "vars": { "DATA": "/mnt/research/panels" },
  "signals": [{ "path": "${DATA}/signal_mom.feather", "...": "..." }]
}
```

把机器相关的根目录收进 `vars`，配置就能在不同机器间直接复用。

### format

留空时按文件后缀推断：

| 后缀 | 格式 |
|---|---|
| `.feather` | `feather` |
| `.parquet`、`.pq` | `parquet` |
| `.csv`、`.txt` | `csv` |
| `.gz`、`.zip` | 取倒数第二个后缀判断，如 `.csv.gz` 读作 `csv` |

后缀无法推断时抛 `ValueError`，此时需显式指定。取值须在对应的 source 注册表中存在。

### column_map

源列名到包内统一列名的映射，写法为 `{"包内列名": "源文件列名"}`。

列名校验在**读取整表之前**完成：先只读表头（feather/parquet 走 Arrow footer，10GB 级面板也是常数开销），确认所有需要的源列都存在，再按列下推读取，只加载用到的列。

- 必需映射缺失 → `ContractError: column_map 缺少必需映射 [...]`
- 映射的源列在文件中不存在 → `ContractError: 源列 [...] 不存在；实际列为 [...]`

可选列（如 `fwd_ret`、`cap`）未映射或源列不存在时静默跳过，不报错。

### read_kwargs

透传给底层读取函数的额外参数：`pd.read_feather`、`pd.read_parquet` 或 `pd.read_csv`。列筛选由 `column_map` 负责下推，不需要在此重复指定。

---

## signals

alpha 信号源列表，**至少一项**，为空时抛 `ContractError`。每项一路信号。

同一文件中的多个 alpha 列对应多项 spec：`path` 相同，`column_map.alpha` 各写各的列名，`name` 互不相同。信号重名时抛 `ContractError`。

### 必需与可选列

| 包内列名 | 必需 | 说明 |
|---|---|---|
| `date` | 是 | 调仓日 |
| `id` | 是 | 资产标识 |
| `alpha` | 是 | 因子值 |
| `fwd_ret` | 否 | 自带的前视收益，`engine.forward_return.source="signals"` 时必需 |

### dropna

`bool`，默认 `true`。丢弃 `date`、`id`、`alpha` 任一缺失的行。

!!! note "源文件缺失率照常统计"

    无论该开关如何设置，源文件的读入行数与缺失行数都会被记录，并在 `bundle.meta["signals"][name]["source_na_rate"]` 中报出。

    该数字报的是**源文件有多脏**，不是产出表里还剩多少 NaN——`dropna` 打开时那些行已被丢弃，只看产出表永远是 0。

### 数据类型归一

读入后统一归一，不依赖源文件的 dtype：

- `date` → `datetime64[ns]`，无法解析的值转为 `NaT`
- `id` → 字符串。浮点型 ID 先四舍五入再转整数再转字符串，避免 `1001.0` 与 `1001` 错位
- `alpha`、`fwd_ret` → `float64`，无法解析的值转为 `NaN`

---

## prices

价格面板。每个 `(date, id)` 一行，存在重复时抛 `ContractError`——重复会让市值关联膨胀。

### close 的三种状态

| `column_map` 中的 `close` | 行为 |
|---|---|
| 已声明且源列存在 | 正常读取，可用于 `forward_return.source="prices"` |
| 未声明 | 视为「无价格序列」，价格面板退化为市值与交易日历的来源，`close` 整列为 NaN |
| 已声明但源列不存在 | 抛 `ContractError` |

第三种情况不会被当成第二种处理：拼写错误不应被静默降级成「没有这一列」。

!!! tip "只有预测结果、没有价格序列时"

    `prices.column_map` 中不写 `close`，把 `engine.forward_return.source` 设为 `"signals"`，再映射信号文件自带的 `fwd_ret` 列即可。

    此时价格面板只承担两件事：关联市值、定义交易日历。

`cap` 始终是可选列，仅市值加权时需要。

### restrict_to_signal_assets

`bool`，默认 `true`。只保留信号中出现过的资产，减少内存占用。

价格面板同时还会按首个调仓日截断——前视收益只往后取数，不需要历史缓冲。两项过滤都在读入后立即执行。

过滤后为空时抛 `ContractError`。

---

## references

外部基准序列列表，默认为空。这里声明的基准会进入结果表，`bucket` 固定为 `REF`，`signal_model` 取 `name`。

!!! info "与内置 S&P 500 基准无关"

    包内自带的 S&P 500 曲线由 Visualizer 直接绘制，不需要在此声明，也不进入结果表。此处配置的是额外的外部基准序列。

### frequency

`str`，默认 `"daily"`，只能取以下两值，其他取值抛 `ContractError`：

=== "daily"

    原始序列为日频收益，需按持有期复利成周期收益。复利窗口为 `[锚点 + engine.reference_lag, 锚点 + lag + horizon)`。

=== "period"

    原始序列已是周期收益，直接按调仓日历对齐取值，不做任何折算。

### 必需列

| 包内列名 | 说明 |
|---|---|
| `date` | 观测日 |
| `ret` | 简单收益 |

`date` 或 `ret` 缺失的行在读入时即被丢弃。

---

## calendar

调仓日历的构建规则。

### source

`str`，默认 `"signals"`。日历基于哪张表的日期集合构建：

- `signals`：取信号文件的日期。信号只在调仓日落盘时用这一项
- `prices`：取价格面板的日期。信号为每日频、需要按固定节奏抽稀时用这一项

### first_rebalance / last_rebalance

`str | null`，默认 `null`。日期字符串（如 `"2021-01-04"`），用于截断日历区间。

`first_rebalance` 留空时取信号的最早日期。`last_rebalance` 留空时不做上界截断。

截断后日历为空时抛 `ContractError`，提示检查区间与数据是否重叠。

### rebalance_freq

`int`，默认 `5`，必须 ≥ 1。调仓间隔，单位为交易日。

!!! warning "应与 `engine.forward_return.horizon` 相等"

    两者不等时相邻两期的持有窗口会重叠或留下空仓缺口，逐期累乘出的净值与最大回撤会失真。引擎会就此告警。详见 [数学口径](../guide/math.md)。

### auto_stride

`bool`，默认 `true`。

信号若只在调仓日落盘，其日期序列的原生间隔可能已经等于或大于 `rebalance_freq`。此时再按 `freq` 抽稀会把周期数又砍掉一倍。

打开该开关后，原生间隔不小于 `rebalance_freq` 时不再二次抽稀。原生间隔定义为相邻日期在交易日历上位置差的中位数。

实际采用的步长与探测到的原生间隔记录在 `bundle.meta["calendar"]` 的 `applied_stride` 与 `native_stride` 中，可用于核对。

---

## 完整示例

```json
{
  "vars": {
    "DATA": "/path/to/your/data"
  },
  "prices": {
    "path": "${DATA}/prices.feather",
    "column_map": {
      "date": "date",
      "id": "id",
      "close": "close",
      "cap": "cap"
    },
    "restrict_to_signal_assets": true
  },
  "signals": [
    {
      "name": "MySignal",
      "path": "${DATA}/signals.feather",
      "column_map": {
        "date": "date",
        "id": "id",
        "alpha": "alpha"
      },
      "dropna": true
    }
  ],
  "references": [],
  "calendar": {
    "first_rebalance": null,
    "last_rebalance": null,
    "rebalance_freq": 5,
    "source": "signals",
    "auto_stride": true
  }
}
```

## 产出

Input Processor 的唯一出口是 `InputBundle`：

| 字段 | 必需列 | 说明 |
|---|---|---|
| `signals` | `date`、`id`、`signal_model`、`alpha` | 多路信号纵向堆叠 |
| `prices` | `date`、`id`、`close`、`cap` | 未映射的列整列为 NaN |
| `calendar` | — | `DatetimeIndex` |
| `references` | `date`、`name`、`ret`、`frequency` | 无外部基准时为 `None` |
| `meta` | — | 各信号的行数、资产数、区间、日历覆盖与源文件缺失率 |
