# MOM —— 12-2 动量

Jiang-Kelly-Xiu (2023) 三个价格类对照因子之一。口径与 `stock_rag_v1` 逐字对齐。

## 因子与收益：两个不同的价格口径

| 环节 | 口径 | 公式 | 对齐的旧项目代码 |
|---|---|---|---|
| **因子值** | 原始 `close`（不复权） | `close[t-21] / close[t-252] - 1` | `Portfolio/benchmarks.py:75-80` |
| **实现收益** | 复权总收益（含分红） | `exp(cum_log_ret[t+5] − cum_log_ret[t]) − 1` | `Data/recompute_labels.py:87-88` |

- 简单收益，不用对数收益（与工具包 Math contract 一致）
- 跳过最近 1 个月（21 个交易日），规避短期反转对动量的污染
- lag 用 `groupby(id).shift(k)` 按个股自身交易行位移，只用过去数据，无前视

### 为什么收益必须复权

`processed_stock_data.feather` 的 `close` 是**未复权原始价**。缩股/拆股会让它跳变：
id=22602 在 2023-12 反向缩股 1:100（`shares` 77868 → 779），`close` 从 $0.0383 跳到
$11.50。若用 `close[t+5]/close[t]-1` 算收益，这一只票会得到 **+25931%** 的假收益，在
493 只等权桶里单独贡献 +64% 的组合收益。

全样本量化：2023 年有 0.05% 的样本点 `close` 日收益与 CRSP `ret` 相差 >50%（拆股），
另有 1.02% 相差 >1%（分红除息）。这些事件集中在低价股，污染全堆在多空腿上。

改复权口径后，同一期 MOM 的 H-L 从 **−141.17%** 回到 **−1.76%**。

旧项目早期也用过 price-only 口径，后来专门写 `recompute_labels.py` 改成复权，并把旧值
备份为 `ret_fwd_price_old` —— 本目录沿用改后的口径。

## 数据源与产物

| 用途 | 路径 |
|---|---|
| 输入价格面板 | `/mnt/.../stock_rag_cache/processed/processed_stock_data.feather`（4980 万行 / 22154 只 / 1992-2025） |
| 输出信号表 | `/mnt/.../portfolio_tool_cache/signals/signal_mom.feather` |
| 回测产物 | `outputs/examples/mom/` |

信号表就是「含 Signal 列的表格」，四列直接对应 InputProcessor 的 signals 契约：

| 列 | dtype | 映射到 | 说明 |
|---|---|---|---|
| `date` | datetime64[ns] | `date` | 调仓日 |
| `id` | int64 | `id` | 包内统一转 str |
| `alpha` | float64 | `alpha` | 因子值 |
| `fwd_ret` | float64 | `fwd_ret` | 复权 5 日实现收益，末尾 5 期为 NaN（覆盖率 99.44%） |

## 回测设置

| 项 | 值 | 出处 |
|---|---|---|
| 回测起点 | 2021-01-04 | `configs/input.json` |
| 调仓频率 | 5 个交易日（251 期） | `configs/input.json` |
| 持有期 | 5 个交易日 | `configs/engine.json` |
| 前视收益来源 | `signals`（用信号表自带的复权 `fwd_ret`） | `configs/engine.json` |
| 分位数 | 10 | `configs/engine.json` |
| 加权方案 | EW / VW / LOGVW | `configs/engine.json` |
| 股票池 | 不过滤（`min_names=20` 兜底） | — |

> ⚠ **持有期是耦合的**：`fwd_ret` 在信号生成时就按 5 日算死了。改 `engine.holding_days`
> 必须同时用 `--holding-days` 重跑 `build_signal.py`，否则年化口径与实际收益不一致。

信号只在调仓日落盘，日历原生间隔已是 5 个交易日，`auto_stride` 会识别到并不再二次抽稀。

## 实测结果（2021-01-04 → 2025-12-24，250 期）

多空腿 H-L：

| 加权 | 年化收益 | 年化波动 | Sharpe | 最大回撤 | 净值 | 换手 | IC |
|---|---|---|---|---|---|---|---|
| EW | 9.2% | 21.5% | 0.43 | −42.0% | 1.41 | 26.5% | 0.029 |
| LOGVW | 11.2% | 22.1% | 0.51 | −34.5% | 1.54 | 26.5% | 0.029 |
| VW | 17.1% | 30.2% | 0.57 | −37.7% | 1.87 | 26.5% | 0.029 |

十分位年化收益（EW）：D0 −7.7% → D8 11.5%，Spearman 秩相关 **0.527**；D9 回落到 1.5%，
即最高动量分位在 2021-2025 表现挣扎 —— 与该期间动量因子的普遍表现一致。

## 运行

```bash
# 后台跑全流程（信号 + 回测），日志在 logs/run_mom.log
nohup bash examples/mom/run.sh > /dev/null 2>&1 &
tail -f examples/mom/logs/run_mom.log

# 信号已生成，只重跑回测
SKIP_BUILD=1 nohup bash examples/mom/run.sh > /dev/null 2>&1 &

# 单步调试
python examples/mom/build_signal.py --stride 5 --holding-days 5 --first-rebalance 2021-01-04
python examples/mom/run_backtest.py --no-render
```

全流程约 19 秒（信号 11s + 回测 8s）。

## 产物清单

`outputs/examples/mom/`：

- `long_short_{ew,vw,logvw}.png` —— 多空腿累计对数收益
- `long_short_equity_{ew,vw,logvw}.png` —— 多空腿净值
- `decile_spread_{ew,vw,logvw}.png` —— 十分位 + H-L 色阶图
- `metrics_by_bucket.csv` —— 各分位 × 加权方案的指标汇总
- `ic_by_period.csv` / `turnover_by_period.csv` —— IC 与换手诊断
- `summary_metrics.csv` / `curves.feather` / `returns.feather` —— 长表原始产物
