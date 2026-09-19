# 多信号

`input.signals` 是列表，每项一路信号。分桶、多空、IC、换手全部按 `signal_model` 分组独立计算，多路信号之间不发生任何混合。

## 声明多路信号

### 来自不同文件

```json
"signals": [
  {
    "name": "MOM",
    "path": "${DATA}/signal_mom.feather",
    "column_map": { "date": "date", "id": "id", "alpha": "alpha" }
  },
  {
    "name": "STR",
    "path": "${DATA}/signal_str.feather",
    "column_map": { "date": "date", "id": "id", "alpha": "alpha" }
  }
]
```

### 来自同一文件的多个 alpha 列

多项 spec 指向同一个 `path`，`column_map.alpha` 各写各的列名：

```json
"signals": [
  {
    "name": "RAG",
    "path": "${DATA}/merged_pred.feather",
    "column_map": { "date": "date", "id": "id", "alpha": "pred_rag" }
  },
  {
    "name": "TGNN",
    "path": "${DATA}/merged_pred.feather",
    "column_map": { "date": "date", "id": "id", "alpha": "pred_tgnn" }
  }
]
```

`name` 必须互不相同，重名时抛 `ContractError`。该名字会出现在结果表的 `signal_model` 列、图例与文件名中。

---

## 哪些计算按信号分组

| 计算 | 分组方式 |
|---|---|
| 截面分桶 | 每个 `(调仓日, 信号)` 独立分桶 |
| 多空腿 | 每路信号各自的高桶减低桶 |
| 组合收益 | 按 `(日, 信号, 桶, 加权方案)` |
| 换手率 | 按 `(信号, 桶)` 的相邻期成分比较 |
| IC | 每个 `(信号, 日)` 的截面相关 |

换言之，加入第二路信号不会改变第一路信号的任何数字。

!!! note "ic_mean 与桶、加权方案无关"

    `summary` 中的 `ic_mean` 按信号分组计算，因此同一信号的所有行共享同一个值——IC 衡量的是 alpha 对截面收益的排序能力，与事后怎么分桶、怎么加权无关。

---

## summary 的形状

每行是一个 `(signal_model, bucket, weight)` 组合，总行数为：

```
信号数 × (分位数 + H-L + 外部基准数) × 加权方案数
```

列结构：

| signal_model | bucket | weight | n_periods | …配置的指标… | turnover | ic_mean |
|---|---|---|---|---|---|---|

两路信号、10 个分位、1 个外部基准、EW 与 VW 两套加权，即 `2 × (10 + 1 + 1) × 2 = 48` 行。

外部基准行的 `signal_model` 取基准名而非信号名，`bucket` 为 `REF`。

---

## 图表如何安排多信号

图表先按**加权方案**切分——EW 的图和 VW 的图永远分开，同口径才谈得上比较。再按图表类型决定多路信号怎么放：

| | 策略对比图（`color_mode: palette`） | 分位图（`color_mode: gradient`） |
|---|---|---|
| 多信号 | 叠在同一张，按信号分配颜色 | **每路信号单独一张** |
| 文件名 | `{name}_{weight}.png` | `{name}_{signal}_{weight}.png` |
| S&P 500 基准 | 画 | 不画 |

判定由 `color_mode` 自动完成。理由是分位图的色阶正是按分位铺开的，再塞进第二路信号既撞色又撞图例；而策略对比图恰恰相反——多路信号必须同图才谈得上比较。

### 两个显式覆盖开关

```json
{
  "name": "decile_spread",
  "type": "cumulative_log_return",
  "color_mode": "gradient",
  "split_by_signal": false,     // 强制挤进同一张
  "show_benchmark": true        // 强制画 S&P 500
}
```

`split_by_signal` 关闭后，色阶仍按分位分配，此时改用**线型**区分信号（实线 / 虚线 / 点划线 / 点线），图例相应变成 `MOM D0` 这样带信号名的形式。

!!! note "拆分只在确有多路信号时发生"

    参与拆分的信号从曲线表中排除 `REF` 桶后统计——外部基准的 `signal_model` 是基准名，不是一路策略。

    去重后只剩一路信号时不拆分，文件名不带信号后缀。

### 文件名中的信号名

信号名进文件名时会做规范化：转小写，非字母数字的字符一律压成单个连字符。

| `name` | 文件名中的形式 |
|---|---|
| `MOM` | `mom` |
| `RAG_v2` | `rag-v2` |
| `12-2 动量` | `12-2` |

全部字符都被压掉时退化为 `signal`。

---

## 一个完整例子

两路信号 + 两套加权 + 两个图表配置：

```json
// visualizer.json
"charts": [
  {
    "name": "long_short",
    "type": "cumulative_log_return",
    "buckets": ["H-L"],
    "color_mode": "palette"
  },
  {
    "name": "decile_spread",
    "type": "cumulative_log_return",
    "buckets": ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "H-L"],
    "color_mode": "gradient"
  }
]
```

产出六张图：

```
long_short_ew.png              # 两路信号叠在一张，带 S&P 500 等权指数
long_short_vw.png              # 同上，带 S&P 500 市值加权指数
decile_spread_mom_ew.png       # MOM 的十分位，色阶铺开，不带基准
decile_spread_mom_vw.png
decile_spread_str_ew.png       # STR 的十分位
decile_spread_str_vw.png
```

数量关系：策略对比图为 `加权方案数` 张，分位图为 `信号数 × 加权方案数` 张。

---

## 按信号过滤

图表与表格都支持只取部分信号：

```json
{
  "name": "mom_only",
  "type": "cumulative_log_return",
  "signals": ["MOM"],
  "buckets": ["H-L"]
}
```

`signals`、`buckets`、`weights` 三个过滤条件依次生效，留空表示不过滤。表格的 `TableSpec` 支持同样的三个字段。

## 下一步

- [产物与落盘](outputs.md)：文件清单与长表结构
- [数学口径](math.md)：指标的确切算法
