# Architecture and data lineage

ATLAS is a batch-analytics system with a read-only serving layer. Models are fitted offline;
the app serves stored runs, so every number on screen traces to a run id and nothing is
re-estimated on request. The one exception is the optimizer, which re-solves over stored
posterior draws when a control changes.

## System

```mermaid
flowchart TB
  subgraph Sources["Sources (never joined)"]
    GA4["GA4 public sample<br/>BigQuery → scripts/extract_ga4.py<br/><i>Observed</i>"]
    CRI["Criteo Uplift v2.1<br/>download → aggregate → delete raw<br/><i>Observed RCT</i>"]
    SIM["Halden simulator<br/>src/atlas/sim (seeded)<br/><i>Simulated</i>"]
  end

  SIM -- observed/ --> DBT
  SIM -. truth/ (grading only) .-> GRADE
  GA4 --> DBT["dbt-duckdb<br/>staging → intermediate → marts<br/>+ reconciliation tests"]
  DBT --> DUCK[("atlas.duckdb<br/>serving warehouse")]

  DUCK --> JOBS
  CRI --> JOBS
  subgraph JOBS["Python batch jobs (src/atlas)"]
    ATT["attribution.py<br/>last-click · Markov"]
    MMM["mmm/<br/>Bayesian MMM in PyMC"]
    GEO["geolift.py<br/>geo-holdout readout"]
    OPT["optimizer.py<br/>exact DP over draws"]
    VOI["voi.py<br/>value of information"]
    ANO["anomaly.py<br/>robust baseline + shift-share"]
    CRT["criteo.py<br/>ITT · IV · uplift"]
  end
  GEO -- lift test --> MMM
  MMM -- posterior draws --> OPT
  MMM -- posterior draws --> VOI
  JOBS --> RUNS[("model_runs/{run_id}/<br/>draws · diagnostics · manifest")]
  GRADE["scorecard<br/>24 randomized worlds"] --> RUNS

  DUCK --> API
  RUNS --> API["FastAPI (read-only)<br/>provenance on every response"]
  API --> WEB["Next.js app<br/>Halden · GA4 · Criteo workspaces"]
  API --> ASK["Ask ATLAS<br/>deterministic analyst"]
```

| Layer | Responsibility | Key guarantee |
|---|---|---|
| Simulator | Generates Halden's observable data and, separately, its causal truth | `truth/` is read only by the scorecard and regret checks |
| dbt | Cleans, deduplicates and models the observable data | Uniqueness, relationship and reconciliation tests gate the build |
| Metric layer | YAML definitions compiled to SQL | Ratios are ratios of sums; each metric is checked against an independent query |
| Batch jobs | Attribution, MMM, experiments, optimization, anomaly detection | Every run writes a manifest (seed, config fingerprint, sampler diagnostics) |
| API | Serves marts and stored runs | Each response carries evidence type, source tables, date range and run id |
| Web | Three workspaces, never blended | A provenance strip on every page shows what kind of evidence is on screen |

## dbt lineage

Generated from `dbt/target/manifest.json`. Sources are on the left, marts on the right.

```mermaid
flowchart LR
  subgraph Halden["Halden · Simulated"]
    s_media[(media_weekly)] --> stg_media[stg_halden__media]
    s_out[(outcomes_weekly)] --> stg_out[stg_halden__outcomes]
    s_sess[(sessions_weekly)] --> stg_sess[stg_halden__sessions]
    s_cal[(calendar_weekly)] --> stg_cal[stg_halden__calendar]
    s_jour[(journeys)] --> stg_jour[stg_halden__journeys]
    stg_jour --> int_touch[int_halden__journey_touches] --> int_lc[int_halden__last_click]
    stg_cal --> dim_week
    seed_ch[[ref.halden_channels]] --> dim_channel
    seed_rg[[ref.halden_regions]] --> dim_region
    stg_media --> fct_cgw[fct_channel_geo_week]
    int_lc --> fct_cgw
    fct_cgw --> fct_cw[fct_channel_week]
    stg_media --> fct_gw[fct_geo_week]
    int_lc --> fct_gw
    stg_out --> fct_gw
    stg_sess --> fct_gw
    fct_gw --> kpi[mart_kpi_weekly]
    dim_week --> kpi
  end

  subgraph GA4["GA4 · Observed"]
    g_sess[(sessions)] --> g_stg_sess[stg_ga4__sessions]
    g_pe[(purchase_events)] --> g_stg_pe[stg_ga4__purchase_events]
    g_pi[(purchase_items)] --> g_stg_pi[stg_ga4__purchase_items]
    g_ifd[(item_funnel_daily)] --> g_stg_ifd[stg_ga4__item_funnel_daily]
    g_ed[(events_daily)] --> g_stg_ed[stg_ga4__events_daily]
    g_tot[(totals)]
    g_stg_pe --> g_rank[int_ga4__purchase_events_ranked]
    g_rank --> g_txn[fct_ga4_transactions]
    g_stg_pi --> g_txn
    g_stg_pi --> g_lines[fct_ga4_item_lines]
    g_txn --> g_lines
    g_stg_ifd --> g_cat[mart_ga4_category_daily]
    g_lines --> g_cat
    g_txn --> g_rfm[mart_ga4_rfm]
    g_stg_sess --> g_funnel[mart_ga4_funnel]
    g_txn --> g_funnel
    g_stg_sess --> g_coh[mart_ga4_cohorts]
    g_txn --> g_coh
    g_stg_sess --> g_daily[mart_ga4_daily]
    g_rank --> g_daily
    g_stg_ed --> g_daily
    g_tot --> g_dq[mart_ga4_data_quality]
    g_rank --> g_dq
    g_stg_sess --> g_dq
    g_stg_pi --> g_dq
  end
```

`int_ga4__purchase_events_ranked` is where the deduplication rule lives (decision D-011): the
earliest purchase event per valid transaction id is kept, and `(not set)`/NULL ids are carried as
*unidentified* rather than silently summed into revenue. `mart_ga4_data_quality` reconciles the
modelled tables back to the extraction totals.

## Model runs

| Run id | What it is |
|---|---|
| `halden-20261023-455a5143` | Flagship Halden decision run: attribution, MMM variants, geo-lift, optimizer, value of information |
| `mmm-halden-dc8353b0` | Bayesian MMM, default priors (ROI ~ LogNormal(0.2, 0.9) for every channel); converged |
| `mmm-halden-8a85883e` | Bayesian MMM, DAG-informed: skeptical ROI prior LogNormal(log 0.35, 0.6) on brand search and retargeting; converged |
| `mmm-halden-6a9bb005` | DAG-informed MMM + lift-test likelihood term for Meta prospecting; converged |
| `scorecard-24w-9a760623` | 24 randomized worlds × methods, graded against truth |
| `anomaly-20261023-d6a9f4ff` | Detector calibrated on 12 incident-free worlds, evaluated on 12 others |
| `criteo-20261023-21b31503` | Criteo RCT readout and uplift models (aggregates only) |

## Reproducing

| Command | Does | Cost |
|---|---|---|
| `make demo` | Runs the app from committed runs | Minutes; no fitting |
| `make build` | Simulator + dbt warehouse + tests | Seconds |
| `make models` | Flagship fits | ~3 min |
| `make scorecard` | 24-world grading | ~1–2 h on 10 cores |
| `make criteo` | Downloads 300 MB, aggregates, deletes the raw file | Network-bound |
| `uv run python scripts/data_dictionary.py` | Regenerates [the data dictionary](data-dictionary.md) | Seconds |
