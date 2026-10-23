# ATLAS — Strategy, Scope & Roadmap

*v0.1 · 2026-10-23 · Living document. Decisions are recorded here with their reasons.*

## 1. Where the portfolio opportunity is in 2026

**What changed in the field**

- Open-source MMM is now a commodity. Google Meridian (Bayesian, geo-hierarchical; v2.x,
  Python 3.11–3.13, GPU recommended) added a no-code **Scenario Planner** in Feb 2026.
  PyMC-Marketing (v1.3.0, Oct 2026) ships lift-test calibration, a budget optimizer and CLV
  models. Meta Robyn (R) remains the ridge-regression + hyperparameter-search alternative.
  → Being able to *run* an MMM is not distinctive. Knowing **when its output is wrong** is.
- Mature teams **triangulate** between methods: MMM for strategic allocation, experiments
  (geo-holdout, conversion lift) for causal calibration, attribution for tactical in-flight
  signals. Both Meridian and PyMC-Marketing explicitly support calibrating with experiments.
- Signal loss (ATT, consent, modelled conversions) weakens user-level attribution, which
  shifts value toward aggregate and experimental methods.
- **GA4 public-sample portfolios are saturated.** Many public repos already do funnel,
  cohort and attribution work on `ga4_obfuscated_sample_ecommerce`. A GA4 dashboard is table stakes.

**Rigorous vs misleading**

| Practice | Verdict |
|---|---|
| Randomized holdout / geo-experiment readout, pre-specified metric, power analysis | Gold standard for one channel and context. Limited by power and external validity |
| Bayesian MMM + informative priors + experiment calibration + holdout validation | Defensible for allocation. Identifiability must be shown, not assumed |
| MMM without experiments, reported as "incremental ROI" | Frequently misleading: seasonal confounding and demand-driven spend |
| Last-click / rule-based / Markov or Shapley "data-driven" attribution | Credit allocation, not causation. Systematically over-credits harvest channels |
| Optimizer on posterior-mean curves, no spend-range guardrails | Misleading: hides uncertainty, extrapolates beyond observed spend |
| Segment decomposition of a metric change | Good triage. It decomposes the change; it does not identify a cause |
| LLM "insights" generated over raw tables | Misleading unless every number comes from a computed, cited endpoint |

**Thesis.** Marketing teams don't lack dashboards or models. They lack a way to know how much
to trust each number and what to do about the uncertainty. In ATLAS every number carries its
**evidence type** (Observed · Attributed · Modeled · Experimental · Simulated · Assumption).
The decision engine treats uncertainty as an input: it recommends an allocation *and* the
experiment that would most improve that recommendation.

## 2. Three concepts

| | A. ATLAS as briefed (6 equal modules) | B. Ground-Truth Measurement Lab + Decision Engine | C. Incrementality-first targeting (Criteo) |
|---|---|---|---|
| Answers the $500K question honestly | Only via synthetic data anyway, but without saying so up front | **Yes, by construction**, and grades its own answer | No (no spend or channels) |
| Analytical depth | Diluted across 6 modules | **High**: attribution, MMM, experiments, optimization, value of information | High but narrow |
| Originality vs public repos | Low–medium | **High**: methods graded against known truth across many worlds | Low–medium (several Criteo repos exist) |
| Data legitimacy risk | High (pressure to blend datasets) | Low: truth is explicit and separated | Low |
| Solo feasibility | Low | Medium–high | High |
| Interview defensibility | Medium | **High**: "here is exactly how wrong method X was" | High |
| Role coverage (MA / PA / DS / marketing science) | Broad but shallow | Strong for marketing science and DS, good for MA | DS-heavy |

## 3. Recommendation

Keep the **ATLAS** name and the six-module surface, but rebuild it around Concept B.
Modules are deliberately **unequal**:

- **C Measurement Lab + D Decision Engine ≈ 60% of effort.** This is the project.
- **A Command Center** is the narrative entry point (small, exact, filterable).
- **B Customer Intelligence** and **E Anomaly Investigation** run on *real* GA4 data, in tight scope.
- **F Analyst** is a thin, controlled layer over the same API, not a separate system.

Challenge to the brief: its own data-integrity rules imply the $500K question can only be
answered inside a simulated business. Make that the **headline feature**, not a footnote.

## 4. Differentiator: "Graded against the truth"

In the simulated company the data-generating process is known and was written down before
any model was fit. On the same data, ATLAS shows:

1. how far last-click, Markov attribution, an uncalibrated MMM and an experiment-calibrated
   MMM each miss the **true** incremental ROI per channel;
2. how much contribution profit the recommended plan leaves on the table (**regret**)
   compared with the true optimum;
3. all of it across **≥ 20 randomized worlds**, including some where MMM fails;
4. **next best experiment**: the lift test with the highest expected value of information
   for next quarter's decision.

Interview line: *"I built a company whose causal truth I knew, then measured which methods
would have misled me, by how much money, and which experiment would fix it."*

## 5. Data strategy and gaps

| Source | Evidence | Use | Cannot support |
|---|---|---|---|
| GA4 obfuscated sample (Google Merchandise Store, 2020-11-01 → 2021-01-31, ≈ 4.3M events) | Observed, real, obfuscated | Funnel, product, device/geo, first-user acquisition, short cohorts, RFM; a **real** anomaly (purchase tracking tails off in late Jan) | Spend, ROAS, CAC, margins, MMM (92 days, no cost). Session attribution: `traffic_source` is the *first-user* source and ≈ 21% is "(data deleted)". Credible LTV |
| Criteo Uplift v2.1 (≈ 14M users, 85/15 randomized, visit/conversion/exposure, CC BY-NC-SA) | Observed RCT | Intent-to-treat lift with CIs, sample-ratio-mismatch check, complier effect for exposed users (treatment as instrument), uplift models with Qini on held-out data, policy value | Revenue/profit, channel mix, any link to a company |
| **Halden Coffee Works**, ATLAS simulator | Simulated, known causal model, seeded | Exec P&L, attribution vs MMM vs geo-lift, optimizer, value of information, anomaly-detector benchmarking with injected anomalies | Any real-world performance claim |
| Meridian / PyMC-Marketing / Robyn sample data | Synthetic (theirs) | Optional check that the MMM pipeline reproduces their tutorials | Primary case study |

Rules: three **separate workspaces**, never joined; a provenance badge on every metric;
Criteo raw data downloaded by script and never redistributed; GA4 extracted with a free
BigQuery sandbox, with only derived marts committed so the demo runs without credentials.

## 6. Analytical questions

**Decision (Halden, simulated)**
1. Given $500K for the next quarter and per-channel min/max limits, which allocation maximizes
   expected incremental contribution profit, on first-order and on 52-week economics?
   What is the P10–P90 range?
2. What is each channel's marginal ROI at current spend, and where does it cross break-even?
3. Which channels does last-click attribution over- or under-credit relative to true
   incrementality, and by how much?
4. How far does an uncalibrated MMM miss per channel, and how much does one geo-lift
   experiment reduce that error?
5. Which single lift test has the highest expected value of information for this decision?
6. Which assumptions (margin, LTV, adstock priors, saturation form) flip the recommendation,
   and at what values?
7. Across N simulated worlds, how much profit does the recommendation leave on the table
   versus the true optimum?

**Real data**
8. (GA4) Where in the funnel is the most potential revenue lost, by device, first-user source
   and category, and is that stable across the three months?
9. (GA4) Which RFM segments concentrate revenue? What is repeat behaviour within the window?
10. (GA4) Is the late-January purchase drop a demand change or a measurement failure, and what
    evidence separates the two?
11. (Criteo) What is the randomized lift in visit and conversion rates, with CIs? What is the
    effect on exposed users (complier effect), under stated IV assumptions?
12. (Criteo) Does uplift-based targeting beat random targeting on held-out data, and by how much?

**Monitoring (Halden)**
13. Which weeks and metrics deviate unusually, and which segments account for it?
    Measure precision and recall against injected anomalies.

## 7. Architecture and stack

```
 BigQuery (GA4)      Criteo download       ATLAS simulator (seeded)
       └──────────────────┼───────────────────────┘
                 data/raw/*.parquet (gitignored, hashed manifests)
                          │
      dbt-duckdb: staging → intermediate → marts   (dbt tests; dbt docs = lineage)
                          │
   Python batch jobs: attribution · MMM (PyMC-Marketing) · experiment readouts · uplift
                      · anomaly · value of information → model_runs/{run_id}/ (draws, diagnostics)
                          │
                 atlas.duckdb (read-only serving DB)
                          │
   FastAPI + Pydantic (/metrics /measurement /optimize /experiments /anomalies /analyst)
                          │  OpenAPI → generated TypeScript types
   Next.js (App Router) · TypeScript · Tailwind · shadcn/ui (Radix) · Recharts
```

| Decision | Choice | Rejected and why |
|---|---|---|
| Warehouse | DuckDB | Postgres: no write workload, adds ops |
| Transformations | dbt-duckdb | Ad-hoc SQL files: no tests or lineage |
| Dataframes | pandas | Polars: no performance need, and a second API |
| MMM | PyMC-Marketing (CPU-feasible, native lift calibration, Hill/geometric, CLV) | Meridian as the main path: GPU-oriented TF stack (kept as an optional cross-check notebook). Robyn: R (its ridge approach is reimplemented as a baseline) |
| Optimizer | NumPy over stored posterior draws plus SciPy SLSQP, at request time | PyMC at request time: too slow for sliders |
| Uplift | scikit-learn meta-learners (S/T/X) | causalml/econml unless clearly needed |
| Anomaly | Seasonal baseline + robust (MAD) residual z-scores, empirical thresholds, shift-share decomposition | Deep-learning detectors: no data to justify them |
| Analyst | Fixed tool registry over the API; deterministic router + templates; optional Claude | Free-form chat over raw tables |
| Testing | pytest + hypothesis, dbt tests, Vitest + Testing Library, one Playwright path | Great Expectations: plain tests suffice |
| Infra | uv, Makefile, Docker Compose, GitHub Actions; Vercel (web) + Fly.io/Render (API with baked DuckDB) | Airflow, Kafka, Spark, Kubernetes, vector DB |

## 8. Product experience

- **Workspace switcher**: *Halden Coffee Works · Simulated* / *Google Merchandise Store ·
  Observed* / *Criteo Incrementality Tests · Observed RCT*. A persistent provenance strip
  shows the evidence type, date range and run id.
- **Narrative navigation**: ① Performance → ② Changes → ③ Evidence → ④ Decision → ⑤ Brief
  (an exportable recommendation memo). The analyst is a drawer reachable from every page.
- **Performance (Command Center)**: few KPIs, each with definition, comparison period and
  evidence badge. A "What changed" list comes from the anomaly engine. The channel table shows
  *last-click ROAS · MMM incremental ROAS (interval) · experiment-measured lift* side by side.
  That gap is the hook.
- **Evidence (Measurement Lab)**: a dot plot of ROI estimates by method per channel, with a
  "reveal truth" toggle in simulated worlds. Response curves with posterior bands and a shaded
  observed-spend range (extrapolation warning). Diagnostics: R-hat, ESS, divergences,
  posterior predictive checks, holdout error vs baselines. The Criteo readout lives here.
- **Decision Engine**: controls (budget, per-channel min/max, objective = revenue /
  first-order profit / 52-week profit, risk posture = expected vs P10, economics assumptions).
  Outputs: current vs proposed, profit distribution with conservative/baseline/optimistic
  = P10/P50/P90 of the posterior (not hand-picked multipliers), marginal ROI vs break-even,
  sensitivity tornado, "How was this calculated?" with run id, and a **Next best experiment**
  card (channel, geo design, duration, power, expected regret reduction in $).
- **Change Investigator**: timeline with expected band, flagged points, a segment
  decomposition waterfall, and hypotheses tagged *Confirmed / Supported / Unverified* with
  suggested diagnostics.
- **Visual identity**: warm-neutral canvas, ink typography (Inter with tabular numerals, IBM
  Plex Mono for ids), one accent plus a fixed evidence-type colour code, light and dark modes,
  dense but calm.

## 9. Roadmap and completion criteria

| Phase | Scope | Done when |
|---|---|---|
| **0 (now)** | Repo, simulator v1, data-generating-process spec, strategy | `make sim` is deterministic per seed; tests and lint green; spec reviewed and frozen |
| **1 Foundation** | GA4 extraction + dbt staging/marts + data tests; Halden order- and touchpoint-level sim; metric definitions → SQL; FastAPI `/metrics`; Next.js shell + Command Center for both workspaces | Every KPI matches an independent SQL check in tests; every filter drives every chart; preview deployed |
| **2 Differentiating analytics** | Criteo readout (sample-ratio check, ITT, CI, complier effect, uplift + Qini); attribution models; MMM v1 + diagnostics + time-split holdout vs naive baselines; truth scorecard over ≥ 20 worlds; anomaly engine (GA4 + injected Halden); GA4 funnel/cohorts/RFM | MMM R-hat < 1.01 with no divergences; holdout beats baselines; multi-world scorecard reproducible; detector precision/recall reported |
| **3 Decision Engine** | Optimizer over draws with constraints, objectives, risk posture; sensitivity; regret vs truth; simulated geo-lift + calibration; value-of-information ranking | Constraints hold under property tests; out-of-range spend flagged; regret reported; value-of-information ranking stable across seeds |
| **4 Polish** | Analyst (deterministic + optional Claude), design pass, accessibility (axe clean), Playwright, README/case study/diagrams/decks/interview prep, deploy | Fresh clone → `make demo` works; live link; no dead controls |

**Minimum exceptional scope**: Phases 0–3 for Halden, the Criteo readout, and a Command
Center. Second tier: GA4 customer intelligence, the anomaly engine, the analyst.

## 10. Top five risks

1. **"You rigged the simulation."** Mitigation: the spec is frozen before fitting; scoring
   runs across randomized worlds, including ones where MMM should fail; failures are
   published; the fitted model's functional forms differ from the truth's in robustness runs.
2. **MMM non-identifiability** (co-moving spend, demand-driven brand search) gives confident
   but wrong ROI. Mitigation: a DAG-informed treatment of harvest channels, geo variation,
   lift-test calibration, parameter-recovery checks, and honest wide intervals.
3. **Optimizer false precision and extrapolation.** Mitigation: optimize expected profit over
   posterior draws, guardrails on observed spend range, a P10 (risk-averse) mode, sensitivity analysis.
4. **GA4 metric errors**: session key = `user_pseudo_id` + `ga_session_id`, event-level vs
   item-level revenue, misreading first-user source as session source, timezone, the
   late-January tracking gap. Mitigation: dbt tests, reconciliation against published counts,
   an explicit exclusion decision.
5. **Breadth creep and front-end/back-end drift.** Mitigation: phase gates, generated
   TypeScript types, contract tests, no new module until the previous phase is green.

## 11. How a senior hiring manager evaluates it

- **60 seconds on the README**: a clear problem, honest provenance, a live link, one striking
  chart (methods vs truth).
- **5 minutes**: does `make demo` work? Are tests meaningful? Is the SQL readable? Are contracts typed?
- **Interview probes**: Why trust your MMM? How did you treat brand search? Why not Markov
  attribution? What's the CI and power on the Criteo lift? What would change with a real
  company's data? What did you get wrong?
- **Red flags**: causal language about attribution; ROI to two decimals without intervals;
  an optimizer recommending 5× historical spend; synthetic data presented as real; dead controls.
- **Green flags**: rejected alternatives documented, failure cases shown, a limitations
  section, reproducibility.

## 12. Deliberately excluded

Real ad-platform API integrations · auth, multi-tenancy, RBAC · streaming or orchestration
frameworks · deep-learning forecasting or anomaly models · Markov/Shapley attribution
presented as a *solution* (they are comparators only) · a second production MMM framework ·
free-form LLM chat or LLM-generated numbers · creative/SEO/influencer tooling · CLV
forecasting on 92 days of GA4 · any blending of GA4, Criteo and Halden into one story.
