# 快速开始

工具包有两条对等的入口——交互式分析用 Python API，批量执行与复现归档用配置目录。两者共用同一套
校验与计算，结果逐值一致。

本页用两个跑通的例子过一遍完整流程：月频面板三路 alpha 同跑，日频面板单路 alpha 配两条基准。
页尾列出这两次运行产出的全部图表。

## 安装

```bash
pip install alpholio
```

需要 Python 3.10 及以上——`pyproject.toml` 声明 `requires-python = ">=3.10"`，CI 在 3.10 / 3.11 /
3.12 / 3.13 四个版本上逐一跑安装与导入冒烟。安装后会注册命令行入口 `alpholio`。

!!! tip "文档中的数据位置是占位符"

    包内与文档内都不含任何本机绝对路径，数据位置一律写作 `/path/to/...`，运行前需指向实际位置。
    JSON 配置用 `vars` 块统一换根目录，Python API 直接传路径或内存表。

    两个例子不附带数据文件，只列出输入表的形态、完整配置与实测结果。

---

## 月频：三路 alpha 同跑

一张月频面板同时充当三路信号与市值来源，每月调仓一次。区间 1998-01 至 2024-11 共 323 个自然月，
每月约 2,800 只。

### 输入

一行一个 `(id, 自然月)`，日期已是月末：

```
date             datetime64[ns]
id                        int64
cap                     float64
fwd_ret                 float64
alpha1                  float64
alpha2                  float64
alpha3                  float64
```

```
      date    id       cap   fwd_ret   alpha1    alpha2    alpha3
1998-01-31 10016 181.90925 -0.037736 1.069835 -2.318964 -1.980191
1998-01-31 10025 241.83650  0.052239 1.072911 -1.840977 -1.366666
1998-01-31 10032 229.72550  0.411290 1.137218  0.186847  1.553281
1998-01-31 10048 283.31250  0.086667 1.183293 -0.461023 -0.629213
1998-01-31 10075 861.58050  0.140496 1.326372  1.753839  1.704253
```

三列 alpha 来自三个不同模型，在包中即三路独立信号。没有 `close` 列：面板自带 `fwd_ret`，
市值加权所需的 `cap` 也在同一张表里，因此价格面板的职责由这张表一并承担——同一份数据既作
`signals` 也作 `prices`。

### 跑起来

=== "Python API"

    三路 alpha 在同一张表的不同列上，`signal_columns` 是全局映射，无法为每路各写一套，
    因此改用 `SignalSpec` 逐路声明：

    ```python
    import pandas as pd
    import alpholio as alp
    from alpholio.config_schema import SignalSpec

    panel = pd.read_parquet("/path/to/data/panel.parquet")

    def spec(name):
        return SignalSpec(
            name=name,
            frame=panel,
            column_map={"date": "date", "id": "id", "alpha": name, "fwd_ret": "fwd_ret"},
        )

    bt = alp.backtest(
        signals=[spec("alpha1"), spec("alpha2"), spec("alpha3")],
        prices=panel,
        price_columns={"date": "date", "id": "id", "cap": "cap"},
        horizon=1,
        frequency="monthly",
    )

    bt.summary(bucket="H-L")            # 多空腿指标
    bt.plot("deciles", signal="alpha2")  # 单路信号的分位结构
    bt.save("/path/to/data/outputs/")    # 图与表落盘
    ```

    三路信号共用同一个 `panel` 对象，不会复制三份。

=== "配置目录"

    目录内固定四个文件名，缺任一即报错。`vars` 中定义的变量以 `${VAR}` 形式在路径里展开，
    便于在不同机器间切换数据根目录。

    `input.json`——三路信号指向同一个文件，只有 `column_map.alpha` 不同：

    ```json
    {
      "vars": { "DATA": "/path/to/your/data" },
      "frequency": "monthly",
      "prices": {
        "path": "${DATA}/panel.parquet",
        "column_map": { "date": "date", "id": "id", "cap": "cap" },
        "restrict_to_signal_assets": true
      },
      "signals": [
        {
          "name": "alpha1",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "alpha1", "fwd_ret": "fwd_ret" }
        },
        {
          "name": "alpha2",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "alpha2", "fwd_ret": "fwd_ret" }
        },
        {
          "name": "alpha3",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "alpha3", "fwd_ret": "fwd_ret" }
        }
      ],
      "references": [],
      "calendar": {
        "first_rebalance": null,
        "last_rebalance": null,
        "rebalance_freq": 1,
        "source": "signals",
        "auto_stride": true
      }
    }
    ```

    `engine.json`——`forward_return.horizon` 为必填项，此处单位是自然月：

    ```json
    {
      "n_buckets": 10,
      "min_names": 20,
      "holding_days": null,
      "weights": ["ew", "vw"],
      "include_references": false,
      "long_short": { "enabled": true, "label": "H-L", "reverse": false },
      "forward_return": { "horizon": 1, "source": "signals", "clip_lower": null }
    }
    ```

    `analyzer.json`：

    ```json
    {
      "metrics": ["ann_ret", "cagr", "ann_vol", "sharpe", "max_drawdown", "total_equity"],
      "periods_per_year": null,
      "trading_days_per_year": 252.0,
      "risk_free_rate": 0.0,
      "diagnostics": { "turnover": true, "ic": true, "ic_min_names": 20 },
      "curves": { "clip_lower": -0.99, "shared_origin": true },
      "vol_rescale": { "enabled": false, "reference": null, "min_periods": 20 }
    }
    ```

    `visualizer.json`——两个图表配置对应两类图：多空腿同图对比走 `palette`，分位结构走 `gradient`
    并逐信号拆图：

    ```json
    {
      "output_dir": "${DATA}/outputs",
      "export_returns": true,
      "charts": [
        {
          "name": "long_short",
          "type": "cumulative_log_return",
          "buckets": ["H-L"],
          "color_mode": "palette",
          "show_baseline": true
        },
        {
          "name": "deciles",
          "type": "cumulative_log_return",
          "buckets": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "H-L"],
          "color_mode": "gradient",
          "legend_ncol": 2
        }
      ],
      "tables": [
        {
          "name": "metrics",
          "type": "summary",
          "percent_columns": ["ann_ret", "cagr", "ann_vol", "max_drawdown", "turnover"],
          "decimals": 4
        },
        { "name": "turnover", "type": "turnover" },
        { "name": "ic", "type": "ic" }
      ],
      "style": { "figsize": [12.0, 6.5], "dpi": 120 }
    }
    ```

    ```bash
    alpholio run --config-dir configs/
    alpholio run --config-dir configs/ --no-render     # 只算不出图
    alpholio run --config-dir configs/ --quiet         # 不打印摘要，仅列出落盘文件
    ```

`frequency: "monthly"` 一处声明，四处生效：`rebalance_freq` 与 `horizon` 的单位变成自然月，
年化基数取 12 而非 252，前视收益按自然月末取数，日频基准的复利窗口按月计。

!!! warning "月频面板漏声明 `frequency` 不会报错"

    沿用默认的 `daily` 时，`horizon=1` 被当成 1 个交易日，年化因子推导出 252/1。这份面板的
    `ann_ret` 会从 0.3910 变成 8.2103、`sharpe` 从 2.5484 变成 11.6781，而 `total_equity`
    与 `max_drawdown` 分毫不变——从单张指标表上看不出哪一栏错了。

### 结果

多空腿，323 期：

| 信号 | 加权 | `ann_ret` | `cagr` | `ann_vol` | `sharpe` | `max_drawdown` | `total_equity` |
|---|---|---|---|---|---|---|---|
| alpha1 | EW | 10.30% | 9.48% | 15.72% | 0.6552 | −45.99% | 11.44 |
| alpha1 | VW | 1.77% | 0.42% | 16.43% | 0.1075 | −60.81% | 1.12 |
| alpha2 | EW | 39.10% | 45.35% | 15.34% | 2.5484 | −11.49% | 23517.44 |
| alpha2 | VW | 20.05% | 20.28% | 17.21% | 1.1655 | −35.72% | 143.98 |
| alpha3 | EW | 31.79% | 34.74% | 18.38% | 1.7297 | −21.95% | 3059.99 |
| alpha3 | VW | 20.24% | 20.21% | 18.76% | 1.0789 | −34.39% | 141.68 |

换手与 IC 按信号给出，与桶和加权方案无关：alpha1 44.85% / 0.0294，alpha2 63.64% / 0.0730，
alpha3 65.16% / 0.0689。

十分位年化收益（等权）：

| 信号 | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | 秩相关 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| alpha1 | 2.15% | 8.01% | 10.71% | 10.17% | 11.66% | 10.67% | 11.02% | 11.79% | 12.70% | 12.45% | 0.903 |
| alpha2 | −12.04% | 1.06% | 5.37% | 8.62% | 9.41% | 11.19% | 14.73% | 16.47% | 19.46% | 27.06% | 1.000 |
| alpha3 | −8.78% | 0.97% | 5.16% | 8.52% | 10.68% | 12.97% | 14.56% | 15.87% | 18.38% | 23.02% | 1.000 |

末列是分位序号与年化收益的 Spearman 秩相关。alpha2 与 alpha3 严格单调，alpha1 的单调性在中间
分位上断开。三路信号的等权表现全都强于市值加权，多空腿的 `max_drawdown` 也从 −11% 一档扩大到
−35% 一档，说明 alpha 主要集中在小市值一侧。

!!! note "月频下 `ann_ret` 与 `cagr` 能差很远"

    `ann_ret` 是单期均值线性放大，与 `sharpe` 同源；`cagr` 是逐期复利折年，与 `total_equity`
    同源。方向由复利凸性与波动拖累的相对大小决定：alpha2 等权 `cagr` 45.35% 高于 `ann_ret`
    39.10%，是凸性主导；alpha1 等权 `cagr` 9.48% 低于 `ann_ret` 10.30%，是波动拖累主导。

    对照外部绩效表前先认准对方报的是哪一个：两套口径在月频下的差距足以被误判成实现缺陷。
    逐项算法见[数学口径](math.md)。

---

## 日频：单路 alpha 配两条基准

日频面板每 5 个交易日调仓一次，区间 2021-01-04 至 2025-12-24 共 250 个调仓期，每期约 4,800 只。
基准两条，等权与市值加权各一条。

### 输入

三张表。信号表每个 `(date, id)` 一行，自带已算好的实现收益：

```
date       datetime64[ns]
id                  int64
alpha             float64
fwd_ret           float64
```

```
      date    id     alpha  fwd_ret
2021-01-04 10026 -0.231237 0.005321
2021-01-04 10028  2.021429 0.120623
2021-01-04 10032 -0.020332 0.081269
2021-01-04 10044 -0.523864 0.102439
2021-01-04 10051 -0.141912 0.051826
```

价格面板逐日，提供交易日历与市值，区间比信号长得多，超出部分由 `first_rebalance` 与信号自身的
日期范围裁掉：

```
date       datetime64[ns]
id                  int64
close             float64
cap               float64
```

基准序列两列即可，日期与该日收益率：

```
      date       ret
1992-01-02  0.000610
1992-01-03  0.006576
1992-01-06 -0.000601
```

!!! note "`fwd_ret` 与 `alpha` 可以走不同的价格口径"

    信号自带 `fwd_ret` 时工具包直接采用，不做任何再加工。该列若按未复权 `close` 计算，拆股与
    缩股会让它跳变：实测一例中某只股票反向缩股 1:100，价格口径据此算出 +25931% 的单只收益，
    在 493 只的等权桶里单独贡献 +64% 的组合收益，使该期多空腿从 −1.76% 变成 −141.17%。
    复权口径 `prod(1 + 日收益) − 1` 天然免疫拆股与除息。口径正确与否在包的职责之外。

### 跑起来

=== "Python API"

    ```python
    import pandas as pd
    import alpholio as alp

    bt = alp.backtest(
        signals={"alpha1": "/path/to/data/alpha1.feather"},
        prices="/path/to/data/prices.feather",
        price_columns={"date": "date", "id": "id", "close": "close", "cap": "cap"},
        horizon=5,
        first_rebalance="2021-01-04",
        references={
            "SPX_EW": pd.read_csv("/path/to/data/spx_ew.csv", parse_dates=["date"]),
            "SPX_VW": pd.read_csv("/path/to/data/spx_vw.csv", parse_dates=["date"]),
        },
        reference_frequency="daily",
    )

    bt.summary(bucket=["H-L", "REF"])
    bt.plot("long_short", weight="EW", signals=["alpha1", "SPX_EW"])
    bt.save("/path/to/data/outputs/")
    ```

    内存表与文件路径可以混用：信号与基准已在内存里，价格面板几百 MB，交给包按需读取即可。

    `save()` 走的是预设图表，两条基准会同时出现在同一张图上。要让等权图只配等权指数，用
    `plot(signals=[...])` 单独出图，或走配置目录按 `weights` 拆成两个图表配置。

=== "配置目录"

    `input.json`——基准在 `references` 中声明，`frequency` 取 `daily` 表示该序列是日收益，
    需按持有期复利后再与调仓日历对齐：

    ```json
    {
      "vars": { "DATA": "/path/to/your/data" },
      "frequency": "daily",
      "prices": {
        "path": "${DATA}/prices.feather",
        "column_map": { "date": "date", "id": "id", "close": "close", "cap": "cap" },
        "restrict_to_signal_assets": true
      },
      "signals": [
        {
          "name": "alpha1",
          "path": "${DATA}/alpha1.feather",
          "column_map": { "date": "date", "id": "id", "alpha": "alpha", "fwd_ret": "fwd_ret" }
        }
      ],
      "references": [
        {
          "name": "SPX_EW",
          "path": "${DATA}/spx_ew.csv",
          "column_map": { "date": "date", "ret": "ret" },
          "frequency": "daily"
        },
        {
          "name": "SPX_VW",
          "path": "${DATA}/spx_vw.csv",
          "column_map": { "date": "date", "ret": "ret" },
          "frequency": "daily"
        }
      ],
      "calendar": {
        "first_rebalance": "2021-01-04",
        "last_rebalance": null,
        "rebalance_freq": 5,
        "source": "signals",
        "auto_stride": true
      }
    }
    ```

    `engine.json`——`reference_lag` 为 1 表示基准的复利窗口从锚点次日起算，与持仓对齐：

    ```json
    {
      "n_buckets": 10,
      "min_names": 20,
      "holding_days": null,
      "weights": ["ew", "vw"],
      "include_references": true,
      "reference_lag": 1,
      "long_short": { "enabled": true, "label": "H-L", "reverse": false },
      "forward_return": { "horizon": 5, "source": "signals", "clip_lower": null }
    }
    ```

    `analyzer.json` 与月频例子相同。

    `visualizer.json`——两个同名的 `long_short` 配置按 `weights` 分开，各用 `signals` 白名单挑
    对应的那条基准：

    ```json
    {
      "output_dir": "${DATA}/outputs",
      "export_returns": true,
      "charts": [
        {
          "name": "long_short",
          "type": "cumulative_log_return",
          "buckets": ["H-L", "REF"],
          "weights": ["EW"],
          "signals": ["alpha1", "SPX_EW"],
          "color_mode": "palette",
          "show_baseline": true
        },
        {
          "name": "long_short",
          "type": "cumulative_log_return",
          "buckets": ["H-L", "REF"],
          "weights": ["VW"],
          "signals": ["alpha1", "SPX_VW"],
          "color_mode": "palette",
          "show_baseline": true
        },
        {
          "name": "deciles",
          "type": "cumulative_log_return",
          "buckets": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "H-L"],
          "color_mode": "gradient",
          "legend_ncol": 2
        }
      ],
      "tables": [
        {
          "name": "metrics",
          "type": "summary",
          "percent_columns": ["ann_ret", "cagr", "ann_vol", "max_drawdown", "turnover"],
          "decimals": 4
        },
        { "name": "turnover", "type": "turnover" },
        { "name": "ic", "type": "ic" }
      ],
      "style": { "figsize": [12.0, 6.5], "dpi": 120 }
    }
    ```

    两个配置同名且 `weights` 互不重叠，产出的 `long_short_ew.png` 与 `long_short_vw.png`
    不会互相覆盖。`signals` 白名单对策略信号与基准名同时生效，因此参与该图的策略必须一并列出。

三处没有写、由数据推出来的默认值：

| 推导项 | 取值 | 依据 |
|---|---|---|
| `rebalance_freq` | 5，等于 `horizon` | 缺省取同值，相邻持有窗口首尾相接 |
| `weights` | `["ew", "vw"]` | 价格面板带 `cap` 列 |
| `forward_return.source` | `signals` | 信号表自带 `fwd_ret`，优先于由 `close` 推算 |

信号只在调仓日落盘，原生间隔已是 5 个交易日，`auto_stride` 识别到后不再二次抽稀。
规则详见[核心概念](concepts.md#按数据推导的默认值)。

### 结果

多空腿与基准，250 期：

| 行 | 加权 | `ann_ret` | `cagr` | `ann_vol` | `sharpe` | `max_drawdown` | `total_equity` |
|---|---|---|---|---|---|---|---|
| alpha1 H-L | EW | 9.23% | 7.11% | 21.53% | 0.4288 | −42.02% | 1.4060 |
| alpha1 H-L | VW | 17.14% | 13.42% | 30.24% | 0.5670 | −37.67% | 1.8676 |
| SPX_EW REF | — | 12.59% | 11.76% | 16.99% | 0.7408 | −19.32% | 1.7360 |
| SPX_VW REF | — | 15.59% | 15.20% | 16.79% | 0.9284 | −23.33% | 2.0175 |

换手 26.48%/期，`ic_mean` 0.0291。

十分位年化收益（等权）：

| 分位 | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 |
|---|---|---|---|---|---|---|---|---|---|---|
| `ann_ret` | −7.72% | 3.37% | 8.09% | 9.38% | 9.03% | 10.06% | 9.90% | 11.64% | 11.45% | 1.51% |

分位序号与年化收益的 Spearman 秩相关为 0.527：单调性主要由低分位一侧贡献，最高分位 D9 回落到
1.51%，低于 D2 至 D8 的任何一档。多空腿的收益因此几乎全部来自空头腿。

!!! note "基准行逐加权复制"

    一条 `references` 会对**每个**加权方案各复制一行，`SPX_EW` 在 EW 与 VW 两套结果里取值相同——
    基准序列本身与组合的加权方案无关。指标表里因此是 4 行基准而非 2 行；上表按行去重只列一次。

---

## 全部图表

图表类型只有一种：累计对数收益曲线。实际决定「画什么」的是 `buckets` 与 `color_mode` 两项，
两种常用组合固化成了两个预设名：

| 预设 | 内容 | 多信号时 | 文件名 |
|---|---|---|---|
| `long_short` | 多空腿与基准同图对比，带零线 | 叠在同一张，按信号配色 | `long_short_{weight}.png` |
| `deciles` | 分位走色阶、多空腿单独强调 | 每路信号单独一张 | `deciles_{signal}_{weight}.png` |

图表数量因此是「策略对比图：加权方案数」加「分位图：信号数 × 加权方案数」。下面两组图即前述两次
运行的全部产物。

### 月频：三路 alpha × 两套加权

=== "等权 EW"

    ![月频多空腿对比，等权](../images/monthly/long_short_ew.png)

    三路信号的多空腿叠在同一张图上，横轴零线是盈亏分界。

    ![alpha1 分位结构，等权](../images/monthly/deciles_alpha1_ew.png)

    ![alpha2 分位结构，等权](../images/monthly/deciles_alpha2_ew.png)

    ![alpha3 分位结构，等权](../images/monthly/deciles_alpha3_ew.png)

    分位图按信号拆成三张：十个分位走色阶，多空腿用高亮色单独强调。

=== "市值加权 VW"

    ![月频多空腿对比，市值加权](../images/monthly/long_short_vw.png)

    ![alpha1 分位结构，市值加权](../images/monthly/deciles_alpha1_vw.png)

    ![alpha2 分位结构，市值加权](../images/monthly/deciles_alpha2_vw.png)

    ![alpha3 分位结构，市值加权](../images/monthly/deciles_alpha3_vw.png)

### 日频：单路 alpha × 两套加权 × 各自的基准

=== "等权 EW"

    ![日频多空腿与等权指数](../images/daily/long_short_ew.png)

    虚线是基准，样式走 `style.reference_color` 与 `style.reference_linestyle`。

    ![日频分位结构，等权](../images/daily/deciles_ew.png)

=== "市值加权 VW"

    ![日频多空腿与市值加权指数](../images/daily/long_short_vw.png)

    ![日频分位结构，市值加权](../images/daily/deciles_vw.png)

单信号时分位图不加信号名后缀，文件名为 `deciles_{weight}.png`。

同一批运行还落了三份 CSV（`metrics` / `turnover` / `ic`）与两份未经加工的长表
（`summary_metrics.csv` / `curves.feather`），清单与命名规则见[产物与落盘](outputs.md)。

## 下一步

- [核心概念](concepts.md)：两条入口的关系、三份契约与扩展点
- [产物与落盘](outputs.md)：落点规则、表的过滤与百分比换算
- [数学口径](math.md)：每个指标的确切公式与失真条件
- [Python API 参考](../reference/api.md)：`backtest()` 逐参数说明与结果对象
