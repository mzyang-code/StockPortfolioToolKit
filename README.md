# stockportfoliotoolkit

Config-driven cross-sectional portfolio backtesting. The toolkit consumes alpha and handles
bucketing, weighting, metrics and charts.

**📖 [Documentation](https://mzyang-code.github.io/StockPortfolioToolKit/)** (Chinese) ｜ [简体中文 README](README.zh-CN.md)

Four modules, one direction of data flow. Each module owns a JSON config and a single
public entry point, so any stage can be swapped without touching the others.

```
InputProcessor ──InputBundle──▶ PortfolioEngine ──EngineResult──▶ Analyzer ──AnalysisResult──▶ Visualizer ──▶ PNG / CSV
   input.json                     engine.json                     analyzer.json                visualizer.json
```

The toolkit consumes alpha only — it never generates signals. Price-based factors such as
MOM / STR / WSTR are ordinary inputs; see [examples/build_jkx_factors.py](examples/build_jkx_factors.py).

## Install

```bash
pip install -e .                      # compatible ranges
pip install -e ".[dev]"               # adds the test suite
pip install -e ".[notebook]"          # adds what quickstart_*.ipynb needs
pip install -e ".[docs]"              # adds the documentation site toolchain
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

## Documentation

The full documentation is written in Chinese. Direct links:

| Page | Contents |
|---|---|
| [Quick start](https://mzyang-code.github.io/StockPortfolioToolKit/guide/quickstart/) | Install through the first equity curve |
| [Concepts](https://mzyang-code.github.io/StockPortfolioToolKit/guide/concepts/) | Four modules, three data contracts, extension points |
| [Preparing input](https://mzyang-code.github.io/StockPortfolioToolKit/guide/prepare-data/) | Signal table format, column mapping, forward-return sources |
| [Multiple signals](https://mzyang-code.github.io/StockPortfolioToolKit/guide/multi-signal/) | Running several alphas at once, and how charts split |
| [Outputs](https://mzyang-code.github.io/StockPortfolioToolKit/guide/outputs/) | File listing, naming rules, long-table structure |
| [Math contract](https://mzyang-code.github.io/StockPortfolioToolKit/guide/math/) | The exact formula behind every metric |
| [Config reference](https://mzyang-code.github.io/StockPortfolioToolKit/reference/config-input/) | Per-field types, defaults and constraints |

## Benchmarks

No market index data is bundled. Benchmark series are supplied by the user through
`input.references`, enter the result table under bucket `REF`, and appear on charts once
`"REF"` is listed in a chart's `buckets`.

Equal-weighted portfolios should be paired with an equal-weighted index and cap-weighted
with a cap-weighted index — only like-for-like comparisons mean anything. A single
`references` entry is replicated across every weighting scheme, so pairing one index per
scheme takes two entries plus two chart configs constraining `weights` and `signals`. See
[Multiple signals](https://mzyang-code.github.io/StockPortfolioToolKit/guide/multi-signal/).

## Building the docs locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

## Tests

```bash
python -m pytest
```

## License

MIT
