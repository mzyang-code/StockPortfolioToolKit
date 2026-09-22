# 月频：多路预测面板

一张月频面板同时充当三路信号与市值来源，每月调仓一次。与[日频示例](daily-mom.md)相比只有两处不同：多了 `frequency="monthly"`，以及三路 alpha 来自同一张表的不同列。

数据为外部模型的预测面板，1998-01 至 2024-11 共 323 个自然月。本页不附带数据文件，只列出输入表的形态与实测结果。

## 输入长什么样

一行一个 `(id, 自然月)`，日期已是月末：

```
date             datetime64[ns]
id                        int64
cap                     float64
fwd_ret                 float64
avg_pred                float64
avg_pred_acm            float64
avg_pred_tgnn           float64
```

```
      date    id       cap   fwd_ret  avg_pred  avg_pred_acm  avg_pred_tgnn
1998-01-31 10016 181.90925 -0.037736  1.069835     -2.318964      -1.980191
1998-01-31 10025 241.83650  0.052239  1.072911     -1.840977      -1.366666
1998-01-31 10032 229.72550  0.411290  1.137218      0.186847       1.553281
1998-01-31 10048 283.31250  0.086667  1.183293     -0.461023      -0.629213
1998-01-31 10075 861.58050  0.140496  1.326372      1.753839       1.704253
```

共 912,948 行 / 323 个月，每月约 2,800 只。三列预测值来自三个模型，在包中即三路独立 alpha：

| 列 | 信号名 |
|---|---|
| `avg_pred` | RAG |
| `avg_pred_acm` | ACM |
| `avg_pred_tgnn` | TGNN |

没有 `close` 列。面板自带 `fwd_ret`，市值加权所需的 `cap` 也在同一张表里，因此价格面板的职责由这张表一并承担——同一个 DataFrame 既传给 `signals` 也传给 `prices`。

## 怎么用

三路 alpha 在同一张表的不同列上，`signal_columns` 是全局映射，无法为每路各写一套，因此改用 `SignalSpec` 逐路声明：

=== "Python API"

    ```python
    import pandas as pd
    import alpholio as alp
    from alpholio.config_schema import SignalSpec

    panel = pd.read_parquet("panel.parquet")

    def spec(name, alpha_col):
        return SignalSpec(
            name=name,
            frame=panel,
            column_map={"date": "date", "id": "id", "alpha": alpha_col, "fwd_ret": "fwd_ret"},
        )

    bt = alp.backtest(
        signals=[
            spec("RAG", "avg_pred"),
            spec("ACM", "avg_pred_acm"),
            spec("TGNN", "avg_pred_tgnn"),
        ],
        prices=panel,
        price_columns={"date": "date", "id": "id", "cap": "cap"},
        horizon=1,
        frequency="monthly",
        metrics=["ann_ret", "cagr", "ann_vol", "sharpe", "max_drawdown", "total_equity"],
    )

    bt.summary(bucket="H-L")
    bt.plot("deciles", signal="ACM")
    ```

    三路信号共用同一个 `panel` 对象，不会复制三份。

=== "JSON 配置"

    `input.json` 里三路信号指向同一个文件，只有 `column_map.alpha` 不同：

    ```json
    {
      "vars": { "DATA": "/path/to/your/data" },
      "prices": {
        "path": "${DATA}/panel.parquet",
        "column_map": { "date": "date", "id": "id", "cap": "cap" }
      },
      "signals": [
        {
          "name": "RAG",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "avg_pred", "fwd_ret": "fwd_ret" }
        },
        {
          "name": "ACM",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "avg_pred_acm", "fwd_ret": "fwd_ret" }
        },
        {
          "name": "TGNN",
          "path": "${DATA}/panel.parquet",
          "column_map": { "date": "date", "id": "id", "alpha": "avg_pred_tgnn", "fwd_ret": "fwd_ret" }
        }
      ],
      "calendar": { "rebalance_freq": 1, "source": "signals", "auto_stride": true },
      "frequency": "monthly"
    }
    ```

    `engine.json` 的 `forward_return.horizon` 取 1，此处单位是自然月：

    ```json
    {
      "n_buckets": 10,
      "min_names": 20,
      "weights": ["ew", "vw"],
      "long_short": { "enabled": true, "label": "H-L" },
      "forward_return": { "horizon": 1, "source": "signals" }
    }
    ```

`frequency="monthly"` 一处声明，四处生效：`rebalance_freq` 与 `horizon` 的单位变成自然月，年化基数取 12 而非 252，日频基准的复利窗口按月计。逐项规则见[数据频率](../guide/frequency.md#一处声明四处生效)。

!!! warning "月频面板漏声明 `frequency` 不会报错"

    沿用默认的 `daily` 时，`horizon=1` 被当成 1 个交易日，年化因子推导出 252/1，这份面板的 `ann_ret` 会从 0.3910 变成 8.2103、`sharpe` 从 2.5484 变成 11.6781，而 `total_equity` 与 `max_drawdown` 分毫不变——从单张指标表上看不出哪一栏错了。完整对照见[数据频率](../guide/frequency.md#月频面板不声明会怎样)。

## 结果怎样

多空腿，323 期：

| 信号 | 加权 | `ann_ret` | `cagr` | `ann_vol` | `sharpe` | `max_drawdown` | `total_equity` |
|---|---|---|---|---|---|---|---|
| ACM | EW | 39.10% | 45.35% | 15.34% | 2.5484 | −11.49% | 23517.44 |
| ACM | VW | 20.05% | 20.28% | 17.21% | 1.1655 | −35.71% | 143.98 |
| RAG | EW | 10.30% | 9.48% | 15.72% | 0.6552 | −45.99% | 11.44 |
| RAG | VW | 1.77% | 0.42% | 16.43% | 0.1075 | −60.81% | 1.12 |
| TGNN | EW | 31.79% | 34.74% | 18.38% | 1.7297 | −21.95% | 3059.99 |
| TGNN | VW | 20.24% | 20.21% | 18.76% | 1.0789 | −34.39% | 141.68 |

换手与 IC 逐信号给出：ACM 63.64% / 0.0730，RAG 44.85% / 0.0294，TGNN 65.16% / 0.0689。

ACM 十分位年化收益（等权）严格单调，分位序号与收益的 Spearman 秩相关为 1.0：

| 分位 | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 |
|---|---|---|---|---|---|---|---|---|---|---|
| `ann_ret` | −12.04% | 1.06% | 5.37% | 8.62% | 9.41% | 11.19% | 14.73% | 16.47% | 19.46% | 27.06% |

三路信号的等权表现全都强于市值加权，多空腿的 `max_drawdown` 也从 −11% 一档扩大到 −35% 一档，说明 alpha 主要集中在小市值一侧。

!!! note "月频下 `ann_ret` 与 `cagr` 能差很远"

    ```
    ann_ret = mean(r) × 12                 单期均值线性放大，与 sharpe 同源
    cagr    = (∏(1 + r))^(12 / n) − 1      逐期复利折年，与 total_equity 同源
    ```

    方向由复利凸性与波动拖累的相对大小决定。ACM 等权 `cagr` 45.35% 高于 `ann_ret` 39.10%，是凸性主导（`(1+m)^12 − 1 > 12m`）；RAG 等权 `cagr` 9.48% 低于 `ann_ret` 10.30%，是波动拖累主导。

    对照外部绩效表前先认准对方报的是哪一个：两套口径在月频下的差距足以被误判成实现缺陷。逐项算法见[数学口径](../guide/math.md)。

## 下一步

- [日频：MOM 12-2 动量](daily-mom.md)：日度口径下的同一套流程
- [多信号](../guide/multi-signal.md)：多路 alpha 同跑时图表如何拆分、基准如何配对
- [数据频率](../guide/frequency.md)：月度口径的取数规则与自然月对齐
