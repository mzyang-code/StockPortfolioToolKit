# alpholio

Cross-sectional portfolio backtesting. The toolkit consumes alpha and handles bucketing,
weighting, metrics and charts.

**📖 [Documentation](https://mzyang-code.github.io/alpholio/)** (Chinese) ｜ [简体中文 README](https://github.com/mzyang-code/alpholio/blob/main/README.zh-CN.md)

Four modules, one direction of data flow. Each module owns a single public entry point,
so any stage can be swapped without touching the others.

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
```

The toolkit consumes alpha only — it never generates signals. Price-based factors such as
MOM / STR / WSTR are ordinary inputs; see the
[daily MOM example](https://mzyang-code.github.io/alpholio/examples/daily-mom/) for one
worked end to end.

## Install

```bash
pip install alpholio
```

Working from a clone instead:

```bash
pip install -e .                      # compatible ranges
pip install -e ".[docs]"              # adds the documentation site toolchain
```

To reproduce the exact verified combination (Python 3.12.2):

```bash
conda env create -f environment.yml
conda activate alpholio
pip install -e .
```

## Quick start

Factor and price tables go in as DataFrames — no need to write them to disk first:

```python
import alpholio as alp

bt = alp.backtest(signals=alpha_df, prices=price_df, horizon=5)

bt.summary()                   # metrics per (signal_model, bucket, weight)
bt.plot("long_short")          # long-short equity curve, returns a matplotlib Figure
bt.plot("deciles")             # per-quantile gradient chart
bt.save("outputs/")            # PNG charts and CSV metrics to disk

bt.returns                     # per-period portfolio returns, long format
bt.curves                      # equity and cumulative log-return curves
```

`horizon` is the measurement window of each period's realised return and is required.
Column mapping is inferred when the source names already match the contract
(`date` / `id` / `alpha`); the rebalance interval defaults to `horizon`; and value
weighting is added automatically when the price table carries a `cap` column.

Monthly panels only need a `frequency`: `horizon` and the rebalance interval then count
calendar months, and metrics annualise at 12 periods per year.

```python
bt = alp.backtest(signals=alpha_df, prices=panel_df, horizon=1, frequency="monthly")
```

File paths work interchangeably with in-memory tables:

```python
bt = alp.backtest(signals="alpha.feather", prices="prices.feather", horizon=5)
bt = alp.backtest(signals={"MOM": mom_df, "REV": rev_df}, prices=price_df, horizon=5)
```

### Batch runs and reproducible archives

The JSON config directory remains a first-class entry point, suited to batch execution
on a server and to shipping alongside a paper:

```bash
alpholio run --config-dir configs/
```

```python
result = alp.run_pipeline("configs/")
```

Both paths share the same validation and computation and agree value for value.
Parameters settled in a notebook export back out into a config directory:

```python
bt.to_config("paper/configs/", data_dir="paper/data/")
```

## Documentation

The full documentation is written in Chinese. Direct links:

| Page | Contents |
|---|---|
| [Quick start](https://mzyang-code.github.io/alpholio/guide/quickstart/) | Install through the first equity curve |
| [Concepts](https://mzyang-code.github.io/alpholio/guide/concepts/) | Four modules, three data contracts, extension points |
| [Preparing input](https://mzyang-code.github.io/alpholio/guide/prepare-data/) | Signal table format, column mapping, forward-return sources |
| [Data frequency](https://mzyang-code.github.io/alpholio/guide/frequency/) | Daily vs monthly: units, alignment rules, annualisation base |
| [Multiple signals](https://mzyang-code.github.io/alpholio/guide/multi-signal/) | Running several alphas at once, and how charts split |
| [Outputs](https://mzyang-code.github.io/alpholio/guide/outputs/) | File listing, naming rules, long-table structure |
| [Math contract](https://mzyang-code.github.io/alpholio/guide/math/) | The exact formula behind every metric |
| [Daily example](https://mzyang-code.github.io/alpholio/examples/daily-mom/) | MOM 12-2 end to end: input shape, call, measured results |
| [Monthly example](https://mzyang-code.github.io/alpholio/examples/monthly-panel/) | Three alphas off one monthly panel, `frequency="monthly"` |
| [Python API](https://mzyang-code.github.io/alpholio/reference/api/) | `backtest()` parameters and the result object |
| [Config reference](https://mzyang-code.github.io/alpholio/reference/config-input/) | Per-field types, defaults and constraints |

## Benchmarks

No market index data is bundled. Benchmark series are supplied by the user through
`input.references`, enter the result table under bucket `REF`, and appear on charts once
`"REF"` is listed in a chart's `buckets`.

Equal-weighted portfolios should be paired with an equal-weighted index and cap-weighted
with a cap-weighted index — only like-for-like comparisons mean anything. A single
`references` entry is replicated across every weighting scheme, so pairing one index per
scheme takes two entries plus two chart configs constraining `weights` and `signals`. See
[Multiple signals](https://mzyang-code.github.io/alpholio/guide/multi-signal/).

## Building the docs locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

## License

MIT
