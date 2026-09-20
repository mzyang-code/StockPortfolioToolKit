# stockportfoliotoolkit

配置驱动的截面投资组合回测工具包。输入端只需提供 alpha，分桶、加权、指标计算与出图由工具包完成。

**📖 [完整文档](https://mzyang-code.github.io/StockPortfolioToolKit/)** ｜ [English](README.md)

四个模块，单向数据流。每个模块拥有独立的 JSON 配置和唯一的公开入口，任何一环都可以单独替换而不影响其他模块。

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
   input.json                     engine.json                     analyzer.json                visualizer.json
```

本包只消费 alpha，不生成任何信号。MOM / STR / WSTR 这类价格因子属于普通输入，与任何外部 alpha 同等对待。

## 安装

```bash
pip install -e .                      # 兼容区间安装
pip install -e ".[dev]"               # 追加测试依赖
pip install -e ".[notebook]"          # 追加跑 quickstart_*.ipynb 的依赖
pip install -e ".[docs]"              # 追加构建文档站的依赖
```

复现经过验证的那一组确切版本（Python 3.12.2 + 全部 85 个测试通过）：

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

## 文档

| 页面 | 内容 |
|---|---|
| [快速开始](https://mzyang-code.github.io/StockPortfolioToolKit/guide/quickstart/) | 从安装到跑出第一张净值曲线 |
| [核心概念](https://mzyang-code.github.io/StockPortfolioToolKit/guide/concepts/) | 四个模块、三份数据契约与扩展点 |
| [准备输入数据](https://mzyang-code.github.io/StockPortfolioToolKit/guide/prepare-data/) | 信号表格式、列映射与两种前视收益口径 |
| [多信号](https://mzyang-code.github.io/StockPortfolioToolKit/guide/multi-signal/) | 一次跑多路 alpha，以及图表如何拆分 |
| [产物与落盘](https://mzyang-code.github.io/StockPortfolioToolKit/guide/outputs/) | 文件清单、命名规则与长表结构 |
| [数学口径](https://mzyang-code.github.io/StockPortfolioToolKit/guide/math/) | 每个指标的确切算法与失真条件 |
| [配置参考](https://mzyang-code.github.io/StockPortfolioToolKit/reference/config-input/) | 逐字段说明类型、默认值与约束 |

## 基准

包内不附带任何市场指数数据。基准由使用者自备，在 `input.references` 中声明后以 `REF` 桶进入结果表，并在图表的 `buckets` 含 `"REF"` 时上图。

等权组合应配等权指数、市值加权组合应配市值加权指数——同口径才谈得上比较。一条 `references` 会对每个加权方案各复制一行，因此两套加权各配一条指数需要声明两条，再用两个图表配置分别限定 `weights` 与 `signals`，见[多信号](https://mzyang-code.github.io/StockPortfolioToolKit/guide/multi-signal/)。

## 本地构建文档

```bash
pip install -e ".[docs]"
mkdocs serve
```

## 测试

```bash
python -m pytest
```

## 许可证

MIT
