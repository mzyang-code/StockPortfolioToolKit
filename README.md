# stockportfoliotoolkit

Config-driven cross-sectional portfolio backtesting. You bring the alpha; the toolkit
handles bucketing, weighting, metrics and charts.

Four modules, one direction of data flow. Each module owns a JSON config and a single
public entry point, so any stage can be swapped without touching the others.

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
   input.json                     engine.json                     analyzer.json                visualizer.json
```

## Install

```bash
pip install -e .                      # compatible ranges
pip install -e ".[dev]"               # adds the test suite
pip install -e ".[notebook]"          # adds what quickstart_*.ipynb needs
```

To reproduce the exact verified combination (Python 3.12.2, all 85 tests passing):

```bash
conda env create -f environment.yml
conda activate stockportfoliotoolkit
pip install -e .
```

## Quick start

```bash
spt run --config-dir configs/
```

```python
from stockportfoliotoolkit import run_pipeline

result = run_pipeline("configs/")
result.analysis.summary        # metrics per (signal_model, bucket, weight)
result.engine.returns          # per-period portfolio returns, long format
result.outputs                 # files written to disk
```

Each stage can also be driven on its own:

```python
from stockportfoliotoolkit import InputProcessor, PortfolioEngine, Analyzer, Visualizer
from stockportfoliotoolkit.config_schema import InputConfig, EngineConfig

bundle = InputProcessor(InputConfig.from_file("configs/input.json")).run()
engine = PortfolioEngine(EngineConfig.from_file("configs/engine.json")).run(bundle)
```

## Input contract

Nothing is hard-coded: point the config at your files and declare a `column_map`.
Formats supported out of the box are `feather`, `parquet` and `csv`.

| Input | Required columns (after mapping) | Notes |
|---|---|---|
| `prices` | `date`, `id`, `close`, `cap` | one row per (date, id); `cap` only needed for cap weighting |
| `signals[]` | `date`, `id`, `alpha` | one entry per signal; `fwd_ret` optional |
| `references[]` | `date`, `ret` | external benchmark series, `frequency` = `daily` or `period` |

The toolkit consumes alpha only — it never generates signals. Price-based factors such
as MOM / STR / WSTR are ordinary inputs; see [examples/build_jkx_factors.py](examples/build_jkx_factors.py).

## Output contract

`returns` is long format, so an arbitrary number of weighting schemes fits in one table:

| date | signal_model | bucket | weight | ret | count |
|---|---|---|---|---|---|

`bucket` is `"0".."n-1"`, plus `"H-L"` for the long-short leg and `"REF"` for benchmarks.
`summary` carries the configured metrics plus `turnover` and `ic_mean`. Turning on
`analyzer.vol_rescale` replaces every return series with its rescaled version rather
than emitting a second set of rows.

## Math contract

These rules hold everywhere and are covered by tests:

- Cross-sectional weighting uses **simple returns only**; log returns are never averaged
  across the cross section.
- Cumulative equity is `(1 + r).cumprod()`. The log scale is a visualization choice
  (`log1p(r).cumsum()`).
- Realised return is pure price: `close[t+h] / close[t] - 1` where
  `h = forward_return.horizon`, independent of the alpha's own forecast horizon.
- `engine.forward_return.horizon` is required — it is the single source of truth for how
  long one period is. `engine.holding_days` inherits it when omitted; setting it to a
  different value only warns, since that means the measurement window and the holding
  period assumed for annualisation are no longer the same thing.
- `input.calendar.rebalance_freq` should equal `horizon`. Otherwise consecutive holding
  windows overlap or leave gaps, and chaining them into one equity curve distorts
  `total_equity` / `max_drawdown` — the engine warns about this.
- Volatility scaling is a single full-sample constant, so it never changes a curve's
  shape or its Sharpe ratio.

## Built-in benchmark

The package ships daily total returns for the CRSP S&P 500 Universe portfolios
(dividends included, 1992-01-02 to 2025-12-31, 8561 trading days, in
`src/stockportfoliotoolkit/data/sp500_daily.csv.gz`). No configuration required.

- **Matched to the weighting scheme**: equal-weighted charts get the equal-weighted index,
  value-weighted charts get the value-weighted one — only then is the comparison like-for-like.
  Unregistered schemes fall back to value-weighted.
- The benchmark is **buy-and-hold**, sampled onto the chart's own date axis, so it is
  independent of the rebalance cadence and immune to overlapping holding windows.
- Its colour (`#000000`) and line style are hardcoded in `benchmark.BENCHMARK_STYLE`;
  neither `style.palette` nor `style.reference_color` can override them.
- Drawn on strategy-comparison charts only. Decile charts decompose a single strategy, so
  they omit it. Override with `charts[].show_benchmark`.
- Dates outside the data's coverage are left as NaN rather than extrapolated.

## Multi-signal charts

Charts split by weighting scheme first, then by chart kind:

| | Comparison charts (`palette`) | Decile charts (`gradient`) |
|---|---|---|
| Multiple signals | overlaid on one figure | **one figure per signal** |
| Filename | `{name}_{weight}.png` | `{name}_{signal}_{weight}.png` |
| S&P 500 benchmark | drawn | omitted |

Resolved from `color_mode`; override with `charts[].show_benchmark` and
`charts[].split_by_signal`. When several signals are forced onto one gradient chart, the
colour ramp still encodes the decile, so signals are separated by **line style** instead.

## Where results go

Leave `visualizer.output_dir` unset and everything lands in an `outputs/` directory
created **next to your first signal file** — beside your data, not wherever the process
happened to be started. Charts and tables sit flat in that one directory.

```
<dir holding your signal files>/
├── signal_mom.feather
└── outputs/                          ← created automatically
    ├── long_short_ew.png
    ├── decile_spread_mom_ew.png
    ├── metrics_by_bucket.csv
    ├── summary_metrics.csv
    └── curves.feather
```

Set `output_dir` explicitly to write elsewhere (`${VAR}` expansion supported). Relative
paths resolve against the process CWD, not the config directory — so either leave it
unset or give an absolute path. Driving `Visualizer(cfg)` directly without `run_pipeline`
gives it no signal path to anchor on, so `output_dir` becomes mandatory there.

## Extension points

Every stage exposes a registry. Register a class and reference it by name in JSON.

| Registry | Base class | Configured by |
|---|---|---|
| `input.ALPHA_SOURCES` / `PRICE_SOURCES` / `REFERENCE_SOURCES` | `AlphaSource` … | `format` |
| `engine.WEIGHTERS` | `Weighter` | `engine.weights` |
| `analyzer.METRICS` | `Metric` | `analyzer.metrics` |
| `visualizer.CHARTS` / `TABLES` | `Chart` / `Table` | `charts[].type` / `tables[].type` |

```python
from stockportfoliotoolkit.engine import WEIGHTERS, Weighter

@WEIGHTERS.register()
class InverseVolWeighter(Weighter):
    name = "inverse_vol"          # results table shows it as INVERSE_VOL

    def weights(self, frame):
        w = 1.0 / frame["cap"].to_numpy()
        return w / w.sum()
```

## Tests

```bash
python -m pytest
```

## License

MIT
