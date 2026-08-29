# WSTR —— 1 周超短期反转

Jiang-Kelly-Xiu (2023) 三个价格类对照因子之一。口径与 `stock_rag_v1` 逐字对齐。

## 因子与收益：两个不同的价格口径

| 环节 | 口径 | 公式 | 对齐的旧项目代码 |
|---|---|---|---|
| **因子值** | 原始 `close`（不复权） | `-(close[t] / close[t-5] - 1)` | `Portfolio/benchmarks.py:75-80` |
| **实现收益** | 复权总收益（含分红） | `exp(cum_log_ret[t+5] − cum_log_ret[t]) − 1` | `Data/recompute_labels.py:87-88` |

- 简单收益，不用对数收益（与工具包 Math contract 一致）
- 取负号：过去 1 周跌得越多，alpha 越高，落在高分位（做多）
- lag 用 `groupby(id).shift(k)` 按个股自身交易行位移，只用过去数据，无前视
- 回看窗口（5 日）与持有期（5 日）等长，是三个因子里换手最高的

### 为什么收益必须复权

`processed_stock_data.feather` 的 `close` 是**未复权原始价**。缩股/拆股会让它跳变：
id=22602 在 2023-12 反向缩股 1:100（`shares` 77868 → 779），`close` 从 $0.0383 跳到
$11.50。若用 `close[t+5]/close[t]-1` 算收益，这一只票会得到 **+25931%** 的假收益。

反转因子受害尤其严重：它天然把暴跌的低价股推到高分位，而缩股正是这类股票的常见操作。
未复权时 WSTR 的 EW 多空腿会算出年化 +369%、净值 ×680 万的荒谬结果。

全样本量化：2023 年有 0.05% 的样本点 `close` 日收益与 CRSP `ret` 相差 >50%（拆股），
另有 1.02% 相差 >1%（分红除息）。

旧项目早期也用过 price-only 口径，后来专门写 `recompute_labels.py` 改成复权，并把旧值
备份为 `ret_fwd_price_old` —— 本目录沿用改后的口径。

## 数据源与产物

| 用途 | 路径 |
|---|---|
| 输入价格面板 | `/mnt/.../stock_rag_cache/processed/processed_stock_data.feather`（4980 万行 / 22154 只 / 1992-2025） |
| 输出信号表 | `/mnt/.../portfolio_tool_cache/signals/signal_wstr.feather` |
| 回测产物 | `outputs/examples/wstr/` |

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
| EW | **31.6%** | 17.6% | **1.80** | −15.6% | 4.42 | 78.9% | 0.024 |
| LOGVW | 26.7% | 17.4% | 1.54 | −16.3% | 3.49 | 78.9% | 0.024 |
| VW | 2.7% | 29.7% | 0.09 | −47.7% | 0.92 | 78.9% | 0.024 |

十分位年化收益（EW）：D0 −20.1% → D9 11.5%，**Spearman 秩相关 0.758，三个因子里单调性
最好**。VW 下降到 0.285，同样体现反转收益集中在小盘股。

> Sharpe 1.80 是**未扣交易成本**的毛值。本因子每期换手 78.9%、一年调仓 50 次，双边成本
> 按 10 bp 估算就要吃掉约 8 个百分点的年化收益，实际可交易性远低于毛值。

## 运行

```bash
# 后台跑全流程（信号 + 回测），日志在 logs/run_wstr.log
nohup bash examples/wstr/run.sh > /dev/null 2>&1 &
tail -f examples/wstr/logs/run_wstr.log

# 信号已生成，只重跑回测
SKIP_BUILD=1 nohup bash examples/wstr/run.sh > /dev/null 2>&1 &

# 单步调试
python examples/wstr/build_signal.py --stride 5 --holding-days 5 --first-rebalance 2021-01-04
python examples/wstr/run_backtest.py --no-render
```

全流程约 19 秒（信号 11s + 回测 8s）。

## 产物清单

`outputs/examples/wstr/`：

- `long_short_{ew,vw,logvw}.png` —— 多空腿累计对数收益
- `long_short_equity_{ew,vw,logvw}.png` —— 多空腿净值
- `decile_spread_{ew,vw,logvw}.png` —— 十分位 + H-L 色阶图
- `metrics_by_bucket.csv` —— 各分位 × 加权方案的指标汇总
- `ic_by_period.csv` / `turnover_by_period.csv` —— IC 与换手诊断
- `summary_metrics.csv` / `curves.feather` / `returns.feather` —— 长表原始产物
