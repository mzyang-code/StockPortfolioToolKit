# alpholio

截面投资组合回测工具包。输入端只需提供 alpha，分桶、加权、指标计算与出图由工具包完成。

**📖 [完整文档](https://mzyang-code.github.io/alpholio/)** ｜ [English](https://github.com/mzyang-code/alpholio/blob/main/README.md)

四个模块，单向数据流。每个模块拥有唯一的公开入口，任何一环都可以单独替换而不影响其他模块。

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
```

本包只消费 alpha，不生成任何信号。月频与日频两个完整例子见[快速开始](https://mzyang-code.github.io/alpholio/guide/quickstart/)。

## 安装

```bash
pip install alpholio
```

从仓库克隆后开发安装：

```bash
pip install -e .                      # 兼容区间安装
pip install -e ".[docs]"              # 追加构建文档站的依赖
```

复现经过验证的那一组确切版本（Python 3.12.2）：

```bash
conda env create -f environment.yml
conda activate alpholio
pip install -e .
```

## 快速开始

因子与价格表直接传 DataFrame，无需先落盘：

```python
import alpholio as alp

bt = alp.backtest(signals=alpha_df, prices=price_df, horizon=5)

bt.summary()                   # 按 (signal_model, bucket, weight) 的指标
bt.plot("long_short")          # 多空净值图，返回 matplotlib Figure
bt.plot("deciles")             # 分位色阶图
bt.save("outputs/")            # 图 PNG 与指标 CSV 落盘

bt.returns                     # 逐期组合收益长表
bt.curves                      # 净值与累计对数收益曲线
```

`horizon` 是每期实现收益的测量期长度，必填。列名与契约一致（`date` / `id` / `alpha`）时无需声明映射；调仓间隔缺省等于 `horizon`；价格表含 `cap` 列时自动加上市值加权。

月度面板加一个 `frequency` 即可，`horizon` / 调仓间隔随之按自然月计，年化按每年 12 期折算：

```python
bt = alp.backtest(signals=alpha_df, prices=panel_df, horizon=1, frequency="monthly")
```

文件路径与内存表等价，两者可混用：

```python
bt = alp.backtest(signals="alpha.feather", prices="prices.feather", horizon=5)
bt = alp.backtest(signals={"MOM": mom_df, "REV": rev_df}, prices=price_df, horizon=5)
```

### 批量执行与复现归档

JSON 配置目录仍是一等入口，适合服务器批量执行与随论文归档：

```bash
alpholio run --config-dir configs/
```

```python
result = alp.run_pipeline("configs/")
```

两条路径共用同一套校验与计算，结果逐值一致。notebook 中定稿的参数可反向导出成配置目录：

```python
bt.to_config("paper/configs/", data_dir="paper/data/")
```

## 文档

| 页面 | 内容 |
|---|---|
| [快速开始](https://mzyang-code.github.io/alpholio/guide/quickstart/) | 安装、月频与日频两个完整例子，以及包能产出的全部图表 |
| [核心概念](https://mzyang-code.github.io/alpholio/guide/concepts/) | 四个模块、三份数据契约与扩展点 |
| [产物与落盘](https://mzyang-code.github.io/alpholio/guide/outputs/) | 文件清单、命名规则与长表结构 |
| [数学口径](https://mzyang-code.github.io/alpholio/guide/math/) | 每个指标的确切公式与失真条件 |
| [Python API](https://mzyang-code.github.io/alpholio/reference/api/) | `backtest()` 逐参数说明与结果对象 |
| [配置参考](https://mzyang-code.github.io/alpholio/reference/config-input/) | 逐字段说明类型、默认值与约束 |

## 基准

包内不附带任何市场指数数据。基准由使用者自备，在 `input.references` 中声明后以 `REF` 桶进入结果表，并在图表的 `buckets` 含 `"REF"` 时上图。

等权组合应配等权指数、市值加权组合应配市值加权指数——同口径才谈得上比较。一条 `references` 会对每个加权方案各复制一行，因此两套加权各配一条指数需要声明两条，再用两个图表配置分别限定 `weights` 与 `signals`，完整配置见[快速开始](https://mzyang-code.github.io/alpholio/guide/quickstart/)。

## 本地构建文档

```bash
pip install -e ".[docs]"
mkdocs serve
```

## 许可证

MIT
