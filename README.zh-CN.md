# stockportfoliotoolkit

配置驱动的截面投资组合回测工具包。你提供 alpha，工具包负责分桶、加权、指标与出图。

四个模块，单向数据流。每个模块拥有独立的 JSON 配置和唯一的公开入口，任何一环都可以
单独替换而不影响其他模块。

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
   input.json                     engine.json                     analyzer.json                visualizer.json
```

## 安装

```bash
pip install -e .                      # 兼容区间安装
pip install -e ".[dev]"               # 追加测试依赖
pip install -e ".[notebook]"          # 追加跑 quickstart_*.ipynb 的依赖
```

要复现经过验证的那一组确切版本（Python 3.12.2 + 全部 85 个测试通过）：

```bash
conda env create -f environment.yml
conda activate stockportfoliotoolkit
pip install -e .
```

## 快速开始

```bash
spt run --config-dir configs/
```

```python
from stockportfoliotoolkit import run_pipeline

result = run_pipeline("configs/")
result.analysis.summary        # 按 (signal_model, bucket, weight) 的指标
result.engine.returns          # 逐期组合收益长表
result.outputs                 # 已落盘的文件清单
```

各阶段也可以单独驱动：

```python
from stockportfoliotoolkit import InputProcessor, PortfolioEngine, Analyzer, Visualizer
from stockportfoliotoolkit.config_schema import InputConfig, EngineConfig

bundle = InputProcessor(InputConfig.from_file("configs/input.json")).run()
engine = PortfolioEngine(EngineConfig.from_file("configs/engine.json")).run(bundle)
```

## 输入

包内没有任何硬编码路径：在配置里指向你的文件并声明 `column_map` 即可。
内置支持 `feather`、`parquet`、`csv` 三种格式。

| 输入 | 映射后必需列 | 说明 |
|---|---|---|
| `prices` | `date`、`id`、`close`、`cap` | 每个 (date, id) 一行；`cap` 仅市值加权时需要 |
| `signals[]` | `date`、`id`、`alpha` | 每个信号一项，`fwd_ret` 可选 |
| `references[]` | `date`、`ret` | 外部基准序列，`frequency` 取 `daily` 或 `period` |

本包只消费 alpha，不生成任何信号。MOM / STR / WSTR 这类价格因子属于普通输入，
生成方式见 [examples/build_jkx_factors.py](examples/build_jkx_factors.py)。

## 输出

`returns` 采用长表，因此任意数量的加权方案都能装进同一张表：

| date | signal_model | bucket | weight | ret | count |
|---|---|---|---|---|---|

`bucket` 取 `"0".."n-1"`，多空腿为 `"H-L"`，外部基准为 `"REF"`。
`summary` 在配置的指标之外，还带有 `turnover` 与 `ic_mean`。打开 `analyzer.vol_rescale`
后，收益序列整体替换为缩放后的版本，而不是并列多输出一套口径。

### 多信号

`input.signals` 是列表，每项一路信号。同一文件里的多个 alpha 列 = 多项 spec 指向同一
`path`、`column_map.alpha` 各写各的列名。分桶、多空、IC、换手全部按 `signal_model` 分组独立计算。

`summary` 每行是一个 `(signal_model, bucket, weight)` 组合，共
`信号数 × (分位数 + H-L + 基准数) × 加权方案数` 行，列为：

| signal_model | bucket | weight | n_periods | …配置的指标… | turnover | ic_mean |
|---|---|---|---|---|---|---|

图表先按**加权方案**切分，再按图表类型决定信号怎么放：

| | 策略对比图（`color_mode` 默认 `palette`） | 分位图（`color_mode: gradient`） |
|---|---|---|
| 多信号 | 叠在同一张，按信号分配颜色 | **每路信号单独一张** |
| 文件名 | `{name}_{weight}.png` | `{name}_{signal}_{weight}.png` |
| S&P 500 基准 | 画 | 不画 |

判定由 `color_mode` 自动完成——分位图的色阶正是按分位铺开的，再塞进第二路信号既撞色又撞图例。
两个行为都能显式覆盖：`charts[].show_benchmark`、`charts[].split_by_signal`。

若确实要把多路信号挤进同一张分位图（`split_by_signal: false`），色阶仍按分位分配，
此时改用**线型**区分信号（实线/虚线/点划线/点线），图例相应变成 `MOM D0` 这样带信号名的形式。

### 保存路径

`visualizer.output_dir` **留空即可**：产物会落到**首路信号文件同级**的 `outputs/`，
跟你的数据放在一起，不随进程当前工作目录漂移。

```
<你的信号文件所在目录>/
├── signal_mom.feather
├── signal_str.feather
└── outputs/                          ← 自动创建
    ├── long_short_ew.png             # 每个 charts[] × 每个加权方案一张
    ├── long_short_vw.png
    ├── decile_spread_mom_ew.png      # 分位图逐信号拆分
    ├── metrics_by_bucket.csv         # 每个 tables[] 一份
    ├── summary_metrics.csv           # export_returns=true 时的完整指标长表
    └── curves.feather                # export_returns=true 时的完整曲线长表
```

图和表**平铺在同一层**，不再分子目录。

要写到别处就显式给 `output_dir`（支持 `${VAR}` 展开）；注意相对路径按进程当前工作目录
解析，不是按配置文件所在目录，所以要么留空用默认，要么写绝对路径。

单独用 `Visualizer(cfg)` 而不走 `run_pipeline` 时，没有信号路径可做锚点，
此时必须显式给 `output_dir`，否则报错——不会悄悄写进当前目录。

## 数学

以下规则在全包范围内成立，并有测试覆盖：

- 截面加权**只用简单收益**，绝不在截面上平均对数收益。
- `engine.forward_return.horizon` 必填，它是全包唯一一处「一期有多长」的定义。
  `engine.holding_days` 留空即继承该值；显式写成别的数只告警不拦截，因为那意味着
  收益的测量期与年化时假定的持有期不是同一件事。
- `input.calendar.rebalance_freq` 应与 `horizon` 相等。不等时相邻两期的持有窗口会
  重叠或留空仓缺口，逐期累乘出来的净值与最大回撤会失真——引擎会就此告警。
- 累计净值走 `(1 + r).cumprod()`；对数刻度只是可视化层的选择（`log1p(r).cumsum()`）。
- 实现收益取纯价格口径 `close[t+h] / close[t] - 1`（`h = forward_return.horizon`），
  与 alpha 自身的预测期解耦。
- 波动率缩放是全样本单一常数，因此不改变曲线形状，也不改变夏普比率。

## 内置基准

包内自带 CRSP S&P 500 Universe 组合日频总收益（含股息，1992-01-02 ~ 2025-12-31，
8561 个交易日，`src/stockportfoliotoolkit/data/sp500_daily.csv.gz`），随 wheel 分发，无需任何配置。

- **按加权方案配对**：EW 组合的图配等权指数，VW 组合的图配市值加权指数——同口径才谈得上比较。
  未登记的加权方案退回市值加权。
- 基准取**买入持有**后按图表日期轴取样，与调仓节奏无关，因此不受重叠持有期影响。
- 颜色（`#000000`）与线型硬编码在 `benchmark.BENCHMARK_STYLE`，
  `style.palette` / `style.reference_color` 都改不动它。
- 默认只画在**策略对比图**上；分位图在拆解单一策略，不画基准。
  用 `charts[].show_benchmark` 可显式开关。
- 图表日期落在数据覆盖区间之外时记 NaN，不外推。

包内数据由 CRSP 导出的 `sp500_daily_{ew,vw}.csv.gz` 汇成（取 `DlyTotRet` 列）。
原始导出文件在本地 `cache/` 下，该目录被 `.gitignore` 排除，不随仓库分发。

## 扩展点

每个阶段都暴露一个注册表。注册自定义类后，在 JSON 里按名字引用即可。

| 注册表 | 基类 | 配置位置 |
|---|---|---|
| `input.ALPHA_SOURCES` / `PRICE_SOURCES` / `REFERENCE_SOURCES` | `AlphaSource` 等 | `format` |
| `engine.WEIGHTERS` | `Weighter` | `engine.weights` |
| `analyzer.METRICS` | `Metric` | `analyzer.metrics` |
| `visualizer.CHARTS` / `TABLES` | `Chart` / `Table` | `charts[].type` / `tables[].type` |

```python
from stockportfoliotoolkit.engine import WEIGHTERS, Weighter

@WEIGHTERS.register()
class InverseVolWeighter(Weighter):
    name = "inverse_vol"          # 结果表里显示为 INVERSE_VOL

    def weights(self, frame):
        w = 1.0 / frame["cap"].to_numpy()
        return w / w.sum()
```

## 测试

```bash
python -m pytest
```

## 许可证

MIT
