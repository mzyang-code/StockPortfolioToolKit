# 产物与落盘

Visualizer 把 `AnalysisResult` 渲染成 PNG 与 CSV，并返回落盘文件清单。图与表平铺在同一层，不分子目录。

## 不落盘也能取用全部结果

交互式分析时产物不必先写到磁盘。`BacktestResult` 保留了每一层的中间产物：

```python
bt = spt.backtest(signals=alpha_df, prices=price_df, horizon=5)

bt.summary()        # 指标表
bt.returns          # 逐期组合收益长表
bt.curves           # 净值与累计对数收益曲线
bt.ic, bt.turnover  # 诊断序列
bt.members          # 逐期分桶成分明细
bt.aligned          # alpha × 前视收益 × 市值 的对齐面板
```

要落盘时再调 `save()`，见下文。

## 落盘位置

| `output_dir` | 走 `run_pipeline` / `save()` | 单独用 `Visualizer(cfg)` |
|---|---|---|
| 留空，输入是文件 | 落到**首路信号文件同级**的 `outputs/` | 抛 `ContractError` |
| 留空，输入是内存 DataFrame | 抛 `ContractError` | 抛 `ContractError` |
| 显式给出 | 按给出的路径 | 按给出的路径 |

输入为文件时留空是推荐做法：产物与数据放在一起，不随进程当前工作目录漂移。

内存 DataFrame 没有数据文件可作落点锚，因此必须显式给出目录——不猜测落点，也不悄悄写进当前
工作目录：

```python
bt.save("outputs/")                              # 显式给出
bt = spt.backtest(..., output_dir="outputs/")    # 或在回测时就定好
```

```
<信号文件所在目录>/
├── signal_mom.feather
├── signal_str.feather
└── outputs/                          ← 自动创建
    ├── long_short_ew.png
    ├── long_short_vw.png
    ├── decile_spread_mom_ew.png
    ├── decile_spread_str_ew.png
    ├── metrics_by_bucket.csv
    ├── summary_metrics.csv
    └── curves.feather
```

锚点选信号文件而非价格面板，因为价格面板通常是多个项目共用的只读数据，不该往里写产物。

!!! warning "相对路径按进程当前工作目录解析"

    显式给出 `output_dir` 时，相对路径**不**按配置文件所在目录解析。从不同目录启动会让产物漂移到不同位置。

    因此建议要么留空使用默认锚点，要么写绝对路径。该字段支持 `${VAR}` 展开。

单独使用 `Visualizer(cfg)` 时没有信号路径可作锚点，此时必须显式给出 `output_dir`，否则报错——不会悄悄写入当前目录。

---

## 图表

每个图表配置 × 每个加权方案产出一张 PNG。`save()` 默认用 `long_short` 与 `deciles` 两个预设，
也可以只要其中之一：

```python
bt.save("outputs/", charts=["long_short"], tables=["summary"])
```

文件名规则：

```
{图表名}_{weight}.png              # 不拆分信号
{图表名}_{signal}_{weight}.png     # 分位图逐信号拆分
```

`weight` 取加权方案标签的小写形式（`EW` → `ew`）。信号名转小写并把非字母数字压成连字符。

拆分规则由 `color_mode` 自动决定，详见[多信号](multi-signal.md#图表如何安排多信号)。

图表数量：

```
策略对比图：加权方案数
分位图：    信号数 × 加权方案数
```

`weights` 留空时取分析结果中出现的全部加权方案。分析结果中一个都没有时抛 `ContractError`。

---

## 数据表

每个 `tables[]` 条目产出一份 CSV，文件名为 `{tables[].name}.csv`。内置三种类型：

=== "summary"

    指标汇总表，每行一个 `(signal_model, bucket, weight)`。

    ```json
    {
      "name": "metrics_by_bucket",
      "type": "summary",
      "percent_columns": ["ann_ret", "ann_vol", "max_drawdown", "turnover"],
      "decimals": 3
    }
    ```

=== "turnover"

    逐期换手率，每行一个 `(signal_model, bucket, date)`。

    ```json
    { "name": "turnover_by_period", "type": "turnover" }
    ```

=== "ic"

    逐期信息系数，每行一个 `(signal_model, date)`，含有效样本数。

    ```json
    { "name": "ic_by_period", "type": "ic" }
    ```

### percent_columns 会改列名

`summary` 表中列在 `percent_columns` 里的字段会乘以 100 并**改名为 `{列名}_pct`**，原列删除：

| 配置前的列 | CSV 中的列 | 取值 |
|---|---|---|
| `ann_ret` | `ann_ret_pct` | `9.2`（而非 `0.092`） |
| `max_drawdown` | `max_drawdown_pct` | `-42.0` |

不在该列表中的指标（如 `sharpe`、`total_equity`、`ic_mean`）保持原始小数。所有数值列按 `decimals` 四舍五入，但仍保持数值型，便于下游再加工。

!!! note "需要原始小数时看 summary_metrics.csv"

    `export_returns` 导出的 `summary_metrics.csv` 是未经百分比换算与舍入的完整表。`tables[]` 产出的是给人看的版本，两者用途不同。

### 过滤

三个字段依次过滤，留空表示不过滤：

```json
{
  "name": "hl_only",
  "type": "summary",
  "buckets": ["H-L", "REF"],
  "weights": ["EW"],
  "signals": ["MOM"]
}
```

---

## 完整长表导出

`export_returns` 默认打开，额外落两份未经加工的原始产物：

| 文件 | 内容 |
|---|---|
| `summary_metrics.csv` | 完整指标长表，无百分比换算、无舍入 |
| `curves.feather` | 完整曲线长表 |

`curves.feather` 的列：

| date | signal_model | bucket | weight | ret | equity | cum_log_ret |
|---|---|---|---|---|---|---|

每条曲线前置一个零点（`equity = 1.0`、`cum_log_ret = 0.0`），横坐标为最早一期的前一个工作日。

---

## Python 侧的产物

两条入口的返回对象携带同样的中间产物，只是取用方式不同：

=== "backtest()"

    ```python
    bt = spt.backtest(signals=alpha_df, prices=price_df, horizon=5)
    ```

    | 字段 | 内容 |
    |---|---|
    | `bt.returns` / `bt.curves` / `bt.ic` / `bt.turnover` | 直接是 DataFrame |
    | `bt.members` / `bt.aligned` | 分桶成分、对齐面板 |
    | `bt.summary(bucket=..., weight=...)` | 指标表，带过滤 |
    | `bt.bundle` / `bt.engine` / `bt.analysis` | 三份原始契约产物 |
    | `bt.config` | 本次实验的完整 `PipelineConfig` |

=== "run_pipeline()"

    ```python
    result = spt.run_pipeline("configs/", render=False)    # 只算不出图
    ```

    | 字段 | 类型 | 内容 |
    |---|---|---|
    | `result.bundle` | `InputBundle` | 标准化后的信号、价格、调仓日历 |
    | `result.engine` | `EngineResult` | 逐期组合收益、成分明细、对齐面板 |
    | `result.analysis` | `AnalysisResult` | 指标汇总、曲线、换手、IC |
    | `result.outputs` | `list[Path]` | 已落盘的文件清单（`render=False` 时为空） |

`bt.returns` 等属性只是 `bt.engine.returns` 的转发，两者是同一个对象。

### 长表结构

组合收益采用长表，因此任意数量的加权方案都能装进同一张表，新增方案不改变表结构：

| date | signal_model | bucket | weight | ret | count |
|---|---|---|---|---|---|

`bucket` 取 `"0".."n-1"`，多空腿为 `"H-L"`，外部基准为 `"REF"`。

```python
returns = result.engine.returns
returns[(returns["bucket"] == "H-L") & (returns["weight"] == "EW")]
```

### 转回宽表

若下游代码需要 `anchor_date` / `decile` / `ew_ret` / `vw_ret` 这类宽表列名：

```python
from stockportfoliotoolkit import to_legacy_wide

wide = to_legacy_wide(result.engine.returns)
```

该函数沿用旧项目的列名，不跟随包内改名。

---

## 导出为配置目录

`to_config()` 把一次实验的完整参数导成四份 JSON，供 `run_pipeline` 复跑或随论文归档：

```python
bt.to_config("paper/configs/", data_dir="paper/data/")
result = spt.run_pipeline("paper/configs/")        # 复现
```

内存 DataFrame 写不进 JSON，因此内存输入时需给出 `data_dir`：表先落盘到该目录，再把路径写进
配置。复现包本就需要数据随行，这一步是该场景的固有要求而非额外负担。

导出的配置包含 `save()` 用的图表与数据表预设，因此复跑时产物与原来一致。

---

## 命令行的输出

```bash
spt run --config-dir configs/
```

默认打印输入摘要（JSON）与 headline 指标（只含 `H-L` 与 `REF` 行），然后逐行列出落盘文件：

```
wrote /path/to/outputs/long_short_ew.png
wrote /path/to/outputs/metrics_by_bucket.csv
```

两个开关：

| 参数 | 作用 |
|---|---|
| `--no-render` | 只算不出图，不产出任何文件 |
| `--quiet` | 不打印摘要与指标，仅列出落盘文件 |

## 下一步

- [数学口径](math.md)：曲线与指标的确切算法
- [核心概念](concepts.md)：三份契约的完整列定义
