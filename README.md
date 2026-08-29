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
pip install -e .          # add [dev] for the test suite
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
from stockportfoliotoolkit.config import InputConfig, EngineConfig

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
- Realised return is pure price: `close[t+h] / close[t] - 1`, independent of the alpha's
  own forecast horizon.
- Volatility scaling is a single full-sample constant, so it never changes a curve's
  shape or its Sharpe ratio.

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
