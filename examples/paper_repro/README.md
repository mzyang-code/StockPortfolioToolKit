# 论文复现 —— 两套年化口径的分辨

把外部预测面板接入工具包，与一篇已发表论文的绩效表逐格对照。40 格里 SR、Ann.Vol、
MDD 三项全部吻合，Ann.Ret 系统性对不上——差异全部来自年化口径，不是实现错误。

这个例子的价值不在数字本身，而在**对照的方法**：三项一致、一项不一致，比四项都不一致
更能定位问题。

## 数据

四个月频预测面板，1998-01 ~ 2024-11 共 323 个月，每行一个 `(permno, eom)`。
两个维度的交叉：图结构（行）× 模型输入特征（列）。

| | CR：仅用最近 1–12 月累计收益（840,973 行） | FC44：全部 44 个公司特征（912,948 行） |
|---|---|---|
| analyst coverage graph | `merged_pred_analyst(1).parquet` | `merged_pred_analyst_44(1).parquet` |
| mutual fund holding graph | `merged_pred_holding(1).parquet` | `merged_pred_holding_44(1).parquet` |

行数差异不是 universe 定义不同：CR 的 `(permno, eom)` 是 FC44 的真子集，仅 FC44 覆盖的
71,975 个样本里 98.4% 落在每只股票入样后的头 11 个月，而月龄 ≥ 12 的样本仅 0.1% 被 CR
排除。构造 1–12 月累计收益需要 12 个月历史，新股因此进不了 CR 那一列，行数差是特征构造
窗口的副产品。

面板不随仓库分发，默认从 `tests/cache/` 读取，用 `--data-dir` 指向别处。所需列：

| 列 | 映射到 | 说明 |
|---|---|---|
| `permno` | `id` | 资产标识 |
| `eom` | `date` | `'1999-06'` 形式的月份串，脚本取月末时间戳 |
| `forward_return` | `fwd_ret` | 面板自带的实现收益，因此 `forward_return_source="signals"` |
| `MarketCap` | `cap` | 市值加权的权重基准 |
| `avg_pred_{low,high,acm,mlp,tgnn}` | `alpha` | 五个模型各一路信号 |

`avg_pred` 与 `avg_pred_low` 在四个文件里逐值相同，是同一路的别名，取后者即可。

## 口径：`ann_ret` 与 `cagr`

同一条收益序列，两种年化方式：

```
ann_ret = mean(r) × 12                 单期均值线性放大，与 sharpe 同源
cagr    = (∏(1 + r))^(12 / n) − 1      逐期复利折年，与 total_equity 同源
```

月频下两者可以差很远，方向由复利凸性与波动拖累的相对大小决定：

| 组合 | `ann_ret` | `cagr` | 论文 | 主导因素 |
|---|---|---|---|---|
| `holding_44` / ACM / 等权 | 39.10% | 45.35% | 45.41% | 凸性，`(1+m)^12 − 1 > 12m` |
| `analyst` / Low / 等权 | 10.00% | 6.29% | 6.37% | 波动拖累，年化波动 27.5% |

论文报的是 `cagr`，换用该口径后平均偏差从 1.80pp 降到 0.09pp。

**论文表格自身混用了两套口径**：SR 按算术年化算（因此与 `sharpe` 逐格对上），Ann.Ret
按复利折年，所以表内 `SR ≠ Ann.Ret / Ann.Vol`。对照任何外部绩效表之前都要先认准这一点，
否则会把口径差异误判成实现缺陷，或反过来照着错误的方向去"修"一个没坏的引擎。

## 对照结果

```
指标                              平均      中位      最大
SR                             0.005    0.003    0.04
Ann.Ret（ann_ret 算术口径）       1.800    1.308    6.31
Ann.Ret（cagr 复利口径）          0.091    0.046    1.37
Ann.Vol                        0.034    0.014    0.39
MDD                            0.145    0.115    0.88
```

SR / Ann.Vol / MDD 三项吻合，说明分桶、加权、前视收益对齐与多空构造都与论文一致。

`cagr` 口径下唯一超过 0.20pp 的一格是 `holding` / VW / High，偏差 1.37pp：论文该列把
High 与 ACM 的 Ann.Ret 都印作 7.68，而按其余三项指标推算 High 应在 6.3 附近，疑为排版
重复。除该格外，其余 39 格最大偏差 0.20pp。

## 运行

```bash
python run_repro.py                                    # 默认读 tests/cache/
python run_repro.py --data-dir /path/to/parquet        # 面板在别处
python run_repro.py --out /tmp/paper_cmp.csv           # 对照明细落盘
```

四个面板各跑一次，五路信号 × 10 分位 × 2 种加权，整体约 3 分钟。

## 口径参数

| 参数 | 取值 | 理由 |
|---|---|---|
| `frequency` | `"monthly"` | 面板一行即一个自然月，年化基数随之取 12 |
| `horizon` | `1` | 一期 = 一个自然月，与调仓间隔相等，净值累乘口径才成立 |
| `forward_return_source` | `"signals"` | 面板自带实现收益，无价格序列可推算 |
| `n_buckets` / `min_names` | `10` / `20` | 十分位，成分不足 20 只的期整期作废 |

多空腿是第 9 桶减第 0 桶，与论文的 decile long-short 一致。未配基准，未扣交易成本，
表中所有数字都是绝对收益——论文同样未扣无风险利率，其 SR 即 `ann_ret / ann_vol`。
