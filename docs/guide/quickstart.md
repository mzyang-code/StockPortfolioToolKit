# 快速开始

本页从零跑通一次完整回测：准备数据、执行、读取产物。

工具包有两条对等的入口——交互式分析用 Python API，批量执行与复现归档用配置目录。两者共用同一套
校验与计算，结果逐值一致。

## 安装

=== "pip"

    ```bash
    pip install alpholio
    ```

    需要 Python 3.10 及以上。

=== "从仓库克隆"

    ```bash
    pip install -e .                      # 兼容区间安装
    pip install -e ".[docs]"              # 追加构建文档站的依赖
    ```

=== "conda（复现已验证版本）"

    ```bash
    conda env create -f environment.yml
    conda activate alpholio
    pip install -e .
    ```

    对应 Python 3.12.2 与已验证的那一组确切版本。

安装后会注册命令行入口 `alpholio`。

!!! tip "文档中的数据位置是占位符"

    包内与文档内都不含任何本机绝对路径，数据位置一律写作 `/path/to/...`，运行前需指向实际位置。
    JSON 配置用 `vars` 块统一换根目录，Python API 直接传路径或内存表。

    两个完整示例——[日频 MOM 动量](../examples/daily-mom.md)与[月频多路预测面板](../examples/monthly-panel.md)——
    列出了输入表的形态与实测结果，但不附带数据文件。

## 准备数据

包内没有任何硬编码路径与列名。三类输入，各自的必需列：

| 输入 | 必需列 | 说明 |
|---|---|---|
| 信号 | `date`、`id`、`alpha` | 每个 (date, id) 一行，`fwd_ret` 可选 |
| 价格面板 | `date`、`id` | `close` 仅价格口径时需要，`cap` 仅市值加权时需要 |
| 基准 | `date`、`ret` | 可选，`frequency` 取 `daily` 或 `period` |

数据可以是内存中的 DataFrame，也可以是磁盘上的文件（`feather`、`parquet`、`csv`），两者对等。

## 跑第一次回测

因子与价格表直接传 DataFrame，无需先落盘：

```python
import alpholio as alp

bt = alp.backtest(signals=alpha_df, prices=price_df, horizon=5)

bt.summary(bucket="H-L")       # 多空腿指标
bt.plot("long_short")          # 净值图，返回 matplotlib Figure
bt.save("outputs/")            # 图与表落盘
```

`horizon` 是每期实现收益的测量期长度（交易日），必填——它定义了「一期有多长」，全包只此一处事实来源。

其余参数多数不必写，因为按数据推导：

| 推导项 | 规则 |
|---|---|
| 列名映射 | 列名已是 `date` / `id` / `alpha` 时自动识别 |
| `rebalance_freq` | 缺省等于 `horizon`，相邻持有窗口首尾相接 |
| `weights` | 价格表含 `cap` 列时加上市值加权，没有则只做等权 |
| 前视收益口径 | 信号自带 `fwd_ret` 时用该列，否则由 `close` 推算 |

这几项各自对应一类容易算错又不报错的情形，理由见 [核心概念](concepts.md#按数据推导的默认值)。
全部可以显式覆盖，且覆盖后原有告警照常发出。

多路 alpha 用映射给出，键即信号名：

```python
bt = alp.backtest(signals={"MOM": mom_df, "REV": rev_df}, prices=price_df, horizon=5)
bt.plot("deciles", signal="MOM")
```

文件路径与内存表等价，可以混用：

```python
bt = alp.backtest(signals="alpha.feather", prices="prices.feather", horizon=5)
```

!!! tip "notebook 里画不出图时"

    `plot()` 返回的 `Figure` 脱离 pyplot 全局状态直接构造，Jupyter 需要先激活 inline 后端
    才会渲染：

    ```python
    %matplotlib inline
    ```

逐参数说明见 [Python API 参考](../reference/api.md)。

## 四份配置

配置目录适合服务器批量执行，以及随论文归档——一份能进版本库、能 diff 的配置比散落在 notebook 里的调用更便于复核。

notebook 中定稿的参数可反向导出，不必手写：

```python
bt.to_config("paper/configs/", data_dir="paper/data/")
```

配置目录内固定四个文件名，缺任一即报错：

```
configs/
├── input.json          数据来源、列映射、调仓日历
├── engine.json         分桶、加权、前视收益口径
├── analyzer.json       指标、诊断、曲线
└── visualizer.json     图表、数据表、样式
```

一份最小可用的 `input.json`：

```json
{
  "vars": { "DATA": "/path/to/your/data" },
  "prices": {
    "path": "${DATA}/prices.feather",
    "column_map": { "date": "date", "id": "id", "close": "close", "cap": "cap" }
  },
  "signals": [
    {
      "name": "MySignal",
      "path": "${DATA}/signals.feather",
      "column_map": { "date": "date", "id": "id", "alpha": "alpha" }
    }
  ],
  "calendar": { "rebalance_freq": 5, "source": "signals" }
}
```

配套的 `engine.json`，其中 `forward_return.horizon` 为必填项：

```json
{
  "n_buckets": 10,
  "min_names": 20,
  "weights": ["ew", "vw"],
  "long_short": { "enabled": true, "label": "H-L" },
  "forward_return": { "horizon": 5, "source": "prices" }
}
```

!!! tip "`rebalance_freq` 与 `horizon` 保持相等"

    上例两者均为 5 个交易日，相邻两期的持有窗口首尾相接。不等时引擎会告警，详见 [engine.json 参考](../reference/config-engine.md)。

`vars` 中定义的变量以 `${VAR}` 形式在路径里展开，便于在不同机器间切换数据根目录。

未知配置项会被直接拒绝并列出可用项，拼写错误不会被静默吞掉：

```
ConfigError: engine: 未知配置项 ['n_bucket']；可用项为 ['forward_return', 'holding_days', ...]
```

`backtest()` 是普通函数，拼错参数名同样在调用处报 `TypeError`。两条路径都不接受静默忽略——
被忽略的参数会让程序退回默认值，照样算出一条看起来正常的净值曲线。

## 运行

=== "命令行"

    ```bash
    alpholio run --config-dir configs/
    alpholio run --config-dir configs/ --no-render     # 只算不出图
    alpholio run --config-dir configs/ --quiet         # 不打印摘要，仅列出落盘文件
    ```

=== "Python"

    ```python
    from alpholio import run_pipeline

    result = run_pipeline("configs/")
    ```

各阶段也可以单独驱动，中间产物在模块间以固定契约传递。配置既可以从 JSON 读，也可以用 Python 直接构造：

```python
from alpholio import InputProcessor, PortfolioEngine
from alpholio.config_schema import EngineConfig, InputConfig

bundle = InputProcessor(InputConfig.from_file("configs/input.json")).run()
engine = PortfolioEngine(EngineConfig.from_file("configs/engine.json")).run(bundle)
```

`bt.bundle` 也可以接到这里复用，扫参数时不必反复读同一份面板：

```python
for n in (5, 10, 20):
    cfg = EngineConfig(n_buckets=n, forward_return=ForwardReturnSpec(horizon=5))
    PortfolioEngine(cfg).run(bt.bundle)
```

## 读取结果

`PipelineResult` 保留了全部中间产物（`backtest()` 的返回对象见 [产物与落盘](outputs.md#python-侧的产物)）：

| 字段 | 类型 | 内容 |
|---|---|---|
| `result.bundle` | `InputBundle` | 标准化后的信号、价格、调仓日历 |
| `result.engine` | `EngineResult` | 逐期组合收益、成分明细、对齐面板 |
| `result.analysis` | `AnalysisResult` | 指标汇总、净值曲线、换手与 IC |
| `result.outputs` | `list[Path]` | 已落盘的文件清单 |

组合收益采用长表，因此任意数量的加权方案都能装进同一张表：

| date | signal_model | bucket | weight | ret | count |
|---|---|---|---|---|---|

`bucket` 取 `"0".."n-1"`，多空腿为 `"H-L"`，外部基准为 `"REF"`。

```python
summary = result.analysis.summary
summary[summary["bucket"] == "H-L"]      # 只看多空腿
```

## 产物落盘位置

输入为文件且 `output_dir` 留空时，产物落到**首路信号文件同级**的 `outputs/`，与数据放在一起，不随进程当前工作目录漂移：

```
<信号文件所在目录>/
├── signal_mom.feather
└── outputs/                          ← 自动创建
    ├── long_short_ew.png             # 每个图表配置 × 每个加权方案一张
    ├── long_short_vw.png
    ├── deciles_mom_ew.png            # 分位图逐信号拆分
    ├── metrics.csv                   # 每个数据表配置一份
    ├── summary_metrics.csv           # 完整指标长表，未经百分比换算与舍入
    └── curves.feather
```

图与表平铺在同一层，不分子目录。

!!! warning "内存 DataFrame 输入时必须显式给出目录"

    此时没有数据文件可作落点锚，`save()` 会报错而不是猜测落点，也不会悄悄写进当前工作目录。

    显式给出 `output_dir` 时，相对路径不按配置文件所在目录解析。跨目录启动会导致产物漂移，因此建议写绝对路径。

## 下一步

- [Python API 参考](../reference/api.md)：`backtest()` 逐参数说明与结果对象
- [核心概念](concepts.md)：两条入口的关系、三份契约与扩展点
- [engine.json 配置参考](../reference/config-engine.md)：分桶、加权与前视收益的逐字段说明
