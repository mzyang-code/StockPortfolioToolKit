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
pip install -e .          # 需要测试套件时加 [dev]
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
from stockportfoliotoolkit.config import InputConfig, EngineConfig

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

## 数学

以下规则在全包范围内成立，并有测试覆盖：

- 截面加权**只用简单收益**，绝不在截面上平均对数收益。
- 累计净值走 `(1 + r).cumprod()`；对数刻度只是可视化层的选择（`log1p(r).cumsum()`）。
- 实现收益取纯价格口径 `close[t+h] / close[t] - 1`，与 alpha 自身的预测期解耦。
- 波动率缩放是全样本单一常数，因此不改变曲线形状，也不改变夏普比率。

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
