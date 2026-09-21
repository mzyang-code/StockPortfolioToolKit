# 数据频率

包内所有「多长」都用期数表示：`horizon` 跨几期、`rebalance_freq` 隔几期调一次仓、每年有几期。一期有多长，由面板的频率决定。

`input.frequency` 声明面板的一行代表多长一段时间，取 `daily` 或 `monthly`，默认 `daily`。

=== "Python API"

    ```python
    bt = spt.backtest(signals=alpha_df, prices=panel_df, horizon=1, frequency="monthly")
    ```

=== "JSON 配置"

    ```json
    {
      "frequency": "monthly",
      "calendar": { "rebalance_freq": 1 }
    }
    ```

## 一处声明，四处生效

| 受影响的项 | `daily` | `monthly` |
|---|---|---|
| `calendar.rebalance_freq` 的单位 | 交易日 | 自然月 |
| `forward_return.horizon`、`holding_days` 的单位 | 交易日 | 自然月 |
| 日频基准的复利窗口 | `horizon` 个交易日 | `horizon` 个自然月 |
| 年化基数（`periods_per_year` 留空时） | `trading_days_per_year`，默认 252 | 12 |

频率沿 `InputBundle` → `EngineResult.meta` → `AnalysisResult.meta` 单向传递，四份配置之间不需要同步同一个值。

## 月频面板不声明会怎样

月频面板沿用默认的 `daily` 时，`horizon=1` 被当成 1 个交易日，年化因子推导出 `252 / 1`：

下表取自一份 1998-01 至 2024-11 的月频预测面板，多空腿等权：

| 指标 | 声明 `monthly` | 沿用 `daily` |
|---|---|---|
| `ann_ret` | 0.3910 | 8.2103 |
| `ann_vol` | 0.1534 | 0.7031 |
| `sharpe` | 2.5484 | 11.6781 |
| `total_equity` | 23517.44 | 23517.44 |
| `max_drawdown` | −0.1149 | −0.1149 |

前三行整体偏移，后两行由逐期累乘得出，不受年化因子影响。**没有任何告警**：从单张指标表上看不出哪一栏错了，因为 `total_equity` 与 `ann_ret` 本就走不同口径（算术年化 vs 几何累乘），不可互相反推。

在 `frequency` 之前，这只能靠手写 `analyzer.periods_per_year: 12` 规避。该字段仍然有效且优先级最高，与声明 `frequency` 的结果逐值相同。

## 月度口径的取数规则

月度口径下一律按自然月对齐，而不是按面板的行数：

| 项 | 规则 |
|---|---|
| 调仓日 | 每个自然月内最后一个可用日期 |
| 前视收益 | 锚点所在月最后一个可用 `close` → `horizon` 个自然月后该月最后一个可用 `close` |
| 市值 | 锚点所在月最后一个可用 `cap` |
| 日频基准 | 从锚点所在月的月末（`reference_lag=1` 时为其次日）复利到目标自然月的月末 |

按自然月而不是按行数平移，是为了让缺月暴露出来：某资产中途缺一个月时，数行数会取到「两个月后」并当成一期正常收益，按自然月则连不上，该期为 `NaN` 并在对齐阶段被丢弃。

## 两种月度形态

### 面板本身就是月频

一行 = 一个资产一个自然月，日期通常是月末。日历原样保留，`rebalance_freq=1` 即每月调仓：

```python
bt = spt.backtest(
    signals={"RAG": panel, "ACM": panel},
    prices=panel,
    horizon=1,
    frequency="monthly",
    signal_columns={"date": "date", "id": "id", "alpha": "avg_pred", "fwd_ret": "fwd_ret"},
    price_columns={"date": "date", "id": "id", "cap": "cap"},
)
```

### 日频价格面板 + 月度调仓

价格面板逐日，信号按月给出。日历自动落到每月最后一个可用日期，前视收益与市值都取月末值：

```python
bt = spt.backtest(signals=monthly_alpha, prices=daily_prices, horizon=1, frequency="monthly")
```

信号落在月内哪一天（月末、月初、或每月第三个交易日）不影响取数——锚点保持在信号自己的日期上，而收益与市值按其所属自然月对齐。`rebalance_freq` 此时数的仍是月，不需要换算成 21 个交易日。

## 与 references[].frequency 的区别

两个字段同名但说的不是一件事：

| 字段 | 取值 | 含义 |
|---|---|---|
| `input.frequency` | `daily` / `monthly` | 整份面板的一行有多长 |
| `input.references[].frequency` | `daily` / `period` | 某条基准序列是日频观测（需复利）还是已折算好的周期收益（直接对齐） |

月度口径下，`period` 基准按自然月对齐取值：基准的月末日期与面板的月末日期不必是同一天，逐字相等会让整条基准对不上而静默消失。

## 其他频率

`FREQUENCIES` 注册表目前只有 `daily` 与 `monthly` 两项。周频、季频面板可先自行聚合成上述两种形态之一，或在该表中补充一项——每项需给出单位名与年化基数两个常量。
