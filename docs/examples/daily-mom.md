# 日频：MOM 12-2 动量

日频面板、每 5 个交易日调仓一次的完整流程。信号是 Jiang-Kelly-Xiu (2023) 的三个价格类对照因子之一，在本包中与任何外部 alpha 同等对待——包只消费 alpha，不生成信号。

数据为美股全市场，2021-01-04 至 2025-12-24 共 250 个调仓期。本页不附带数据文件，只列出输入表的形态与实测结果。

## 输入长什么样

两张表。信号表每个 `(date, id)` 一行，自带已算好的实现收益：

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

共 1,211,662 行 / 251 个调仓日，每期成分数中位数约 4,800 只。列名已与契约一致（`date` / `id` / `alpha`），因此无需声明列映射。

价格面板逐日，提供交易日历与市值：

```
date       datetime64[ns]
id                  int64
close             float64
cap               float64
```

```
      date    id  close      cap
1992-01-02 10001 14.500 15587.50
1992-01-03 10001 14.500 15587.50
1992-01-06 10001 14.500 15587.50
1992-01-07 10001 14.500 15587.50
1992-01-08 10001 15.125 16259.38
```

共 49,799,062 行 / 22,154 只。区间比信号长得多，超出部分由 `first_rebalance` 与信号自身的日期范围裁掉。

信号表两列的口径：`alpha` 取 `close[t-21] / close[t-252] - 1`，跳过最近一个月以规避短期反转；`fwd_ret` 取此后 5 个交易日的复权总收益。两者走不同的价格口径，原因见[下方](#收益口径为何必须复权)。

## 怎么用

=== "Python API"

    ```python
    import pandas as pd
    import alpholio as alp

    mom = pd.read_feather("signal_mom.feather")

    bt = alp.backtest(
        signals={"MOM": mom},
        prices="processed_stock_data.feather",
        price_columns={"date": "date", "id": "id", "close": "close", "cap": "cap"},
        horizon=5,
        first_rebalance="2021-01-04",
    )

    bt.summary(bucket="H-L")      # 多空腿指标
    bt.plot("long_short")         # 净值图，返回 matplotlib Figure
    bt.save("outputs/")           # 图与表落盘
    ```

    内存表与文件路径可以混用：信号已在内存里，价格面板 10 GB，交给包按需读取即可。

=== "JSON 配置"

    `input.json`：

    ```json
    {
      "vars": { "DATA": "/path/to/your/data" },
      "prices": {
        "path": "${DATA}/processed_stock_data.feather",
        "column_map": { "date": "date", "id": "id", "close": "close", "cap": "cap" },
        "restrict_to_signal_assets": true
      },
      "signals": [
        {
          "name": "MOM",
          "path": "${DATA}/signal_mom.feather",
          "column_map": { "date": "date", "id": "id", "alpha": "alpha", "fwd_ret": "fwd_ret" }
        }
      ],
      "calendar": { "first_rebalance": "2021-01-04", "rebalance_freq": 5, "source": "signals" }
    }
    ```

    `engine.json`：

    ```json
    {
      "n_buckets": 10,
      "min_names": 20,
      "weights": ["ew", "vw"],
      "long_short": { "enabled": true, "label": "H-L" },
      "forward_return": { "horizon": 5, "source": "signals" }
    }
    ```

    ```bash
    alpholio run --config-dir configs/
    ```

三处没有写、由数据推出来的默认值：

| 推导项 | 取值 | 依据 |
|---|---|---|
| `rebalance_freq` | 5，等于 `horizon` | 缺省取同值，相邻持有窗口首尾相接 |
| `weights` | `["ew", "vw"]` | 价格面板带 `cap` 列 |
| `forward_return.source` | `signals` | 信号表自带 `fwd_ret`，优先于由 `close` 推算 |

信号只在调仓日落盘，原生间隔已是 5 个交易日，`auto_stride` 识别到后不再二次抽稀。规则详见[核心概念](../guide/concepts.md#按数据推导的默认值)。

## 结果怎样

多空腿，250 期：

| 加权 | `ann_ret` | `cagr` | `ann_vol` | `sharpe` | `max_drawdown` | `total_equity` | `hit_rate` |
|---|---|---|---|---|---|---|---|
| EW | 9.23% | 7.11% | 21.53% | 0.4288 | −42.02% | 1.4060 | 57.2% |
| VW | 17.14% | 13.42% | 30.24% | 0.5670 | −37.67% | 1.8676 | 52.8% |

换手 26.48%/期，`ic_mean` 0.0291。

十分位年化收益（等权）：

| 分位 | D0 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 |
|---|---|---|---|---|---|---|---|---|---|---|
| `ann_ret` | −7.72% | 3.37% | 8.09% | 9.38% | 9.03% | 10.06% | 9.90% | 11.64% | 11.45% | 1.51% |

分位序号与年化收益的 Spearman 秩相关为 0.527：单调性主要由低分位一侧贡献，最高分位 D9 回落到 1.51%，低于 D2 至 D8 的任何一档。多空腿的收益因此几乎全部来自空头腿，与 2021–2025 年间动量因子的普遍表现一致。

!!! note "`ann_ret` 与 `cagr` 为何不等"

    `ann_ret = mean(r) × 50.4` 是单期均值线性放大，与 `sharpe` 同源；`cagr = (∏(1+r))^(50.4/n) − 1` 是逐期复利折年，与 `total_equity` 同源。此处 `periods_per_year` 由 252/5 推出。两者在波动较大的序列上会系统性分开，逐项算法见[数学口径](../guide/math.md)。

## 收益口径为何必须复权

信号表的 `alpha` 用原始 `close`，`fwd_ret` 用复权总收益——两列刻意走不同口径。

若 `fwd_ret` 也按 `close[t+5]/close[t]-1` 计算，未复权价格遇到拆股与缩股会跳变。实测一例：某只股票在 2023-12 反向缩股 1:100，`shares` 从 77,868 变为 779，`close` 从 \$0.0383 跳到 \$11.50。价格口径据此算出 **+25931%** 的单只收益，在 493 只的等权桶里单独贡献 +64% 的组合收益，使该期多空腿从 **−1.76%** 变成 **−141.17%**。

全样本量化：2023 年有 0.05% 的样本点日收益与 CRSP `ret` 相差超过 50%（拆股），另有 1.02% 相差超过 1%（分红除息）。这些事件集中在低价股，污染因此全部堆在多空腿上。

复权口径 `exp(cum_log_ret[t+h] − cum_log_ret[t]) − 1` 等价于 `prod(1 + 日收益) − 1`，天然免疫拆股与除息。包对此不作判断——`fwd_ret` 列由使用者提供，口径正确与否在包的职责之外。相关取舍见[准备输入数据](../guide/prepare-data.md#两种前视收益口径)。

!!! warning "持有期是耦合的"

    `fwd_ret` 在信号生成时就按 5 日算死了。改 `engine.holding_days` 必须同时重算该列，否则年化口径与实际收益不是同一件事。引擎在两者显式不等时告警但不中断，理由见 [engine.json 参考](../reference/config-engine.md)。

## 下一步

- [月频：预测面板](monthly-panel.md)：同一套 API 在月度口径下的写法
- [数据频率](../guide/frequency.md)：`horizon` 的单位与年化基数如何随频率改变
- [产物与落盘](../guide/outputs.md)：`save()` 写出的文件清单与命名规则
