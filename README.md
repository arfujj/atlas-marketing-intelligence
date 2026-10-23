# ATLAS — Marketing Intelligence & Decision Engine

> From marketing performance to marketing decisions.

**Status: Phase 0 (simulator + strategy).** The full README is written in Phase 4.

ATLAS keeps three data sources strictly separate and never blends them:

| Workspace | Evidence type | Used for |
|---|---|---|
| Halden Coffee Works | **Simulated** — fictional company, known causal truth | Exec P&L, attribution vs MMM vs experiments, budget decisions |
| Google Merchandise Store (GA4 public sample) | **Observed** — real, obfuscated, Nov 2020–Jan 2021 | Funnel, customer behaviour, real anomaly investigation |
| Criteo Uplift v2.1 | **Observed RCT** — real randomized incrementality tests | Experiment readout, uplift targeting |

- Strategy and roadmap: [`docs/00-strategy.md`](docs/00-strategy.md)
- Simulated world spec (pre-registered before any model is fit): [`docs/data-generating-process.md`](docs/data-generating-process.md)

## Quickstart

```bash
make setup   # uv sync (Python 3.12)
make test
make sim     # writes data/synthetic/halden/{observed,truth}/*.parquet + manifest.json
```
