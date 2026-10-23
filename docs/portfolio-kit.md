# Portfolio kit

Material for presenting ATLAS. Every number comes from a committed run (ids in
[the case study](case-study.md)). Halden figures are **simulated** and must always be
described that way; GA4 and Criteo figures are **observed**. Do not convert simulated gains
into claims about real business impact.

## Resume bullets

Pick 3–4. Each one says what was built, how it was validated, and the result, labelled by
evidence type.

- Built **ATLAS**, a marketing-measurement platform that grades attribution, Bayesian MMM and
  experiments against a pre-registered simulated ground truth across 24 randomized worlds.
  It showed that last-click over-credits brand search ~38× ($18.96 vs a true $0.50 per dollar).
- Wrote a Bayesian marketing mix model in **PyMC** (adstock, Hill saturation, ROI-parameterised
  priors, geo-lift calibration likelihood). DAG-informed priors cut mean ROI error from 1.05 to
  0.46, with 89% coverage of a nominal 90% interval (simulated).
- Built an exact **budget optimizer over 1,000 posterior draws**, with spend-range guardrails,
  P10/P90 outcomes and a value-of-information ranking that picks the next experiment by net dollar value.
- Modelled the **GA4 public ecommerce sample** in dbt-duckdb with reconciliation tests (events,
  users and sessions match published totals exactly). Found 335 duplicate transactions (revenue
  $307.6K deduplicated vs $362.2K naive) and traced a late-January revenue drop to
  instrumentation, not demand.
- Analysed a **13.98M-user randomized ad experiment** (Criteo): +27.1% visits (95% CI 26.2–28.0%).
  Used an instrumental-variable estimate to correct a naive exposed-vs-control comparison
  (+37.6 → +28.7 pp), and uplift models with held-out Qini evaluation.
- Shipped a typed **FastAPI + Next.js** product with provenance on every number, 241 pytest
  tests, dbt data tests, Playwright and axe accessibility checks, Docker, and a deterministic
  analyst that never generates numbers itself.

## One-line pitch

> I built a company whose causal truth I knew, then measured which marketing-measurement methods
> would have misled me, by how much money, and which experiment would fix it.

## 30-second pitch

Marketing teams spend millions on what attribution dashboards tell them, but attribution
measures credit, not causation. I built ATLAS to make that gap measurable. A simulated coffee
company with a known causal structure lets me grade every method against the truth. Last-click
says brand search returns $19 per dollar; it returns 50 cents. A Bayesian MMM with the right
priors gets within about 0.46 per dollar on average across 24 randomized worlds. The
platform then turns the model's uncertainty into a budget recommendation, and into the one
experiment worth running next. Real public data (GA4, and a 14-million-user randomized ad
test) is analysed alongside it, never blended in.

## 5-minute recruiter presentation

| Time | Slide | Say | Show |
|---|---|---|---|
| 0:00–0:40 | **The problem** | "Which channels actually drive sales? Dashboards answer a different question: who touched the customer last." | One sentence on screen |
| 0:40–1:20 | **Why it's hard** | "Real data never reveals the true answer, so you can't tell which method is right. I solved that by simulating a company whose truth I wrote down first." | Halden summary: 156 weeks, 10 regions, 6 channels, pre-registered |
| 1:20–2:30 | **The headline** | "Same data, six methods. Last-click says brand search returns $19 per dollar. The truth is 50 cents. Budgets built on last-click do worse than just keeping the current plan in 83% of worlds." | `docs/img/roi-vs-truth.png` |
| 2:30–3:30 | **The decision** | "For the $500K question, the model moves money into non-brand search and TikTok. Expected +$55K, with a range of +$8K to +$108K. Graded against the truth it earned +$13K. That gap is why the next slide exists." | Decision page screenshot |
| 3:30–4:15 | **What to test next** | "It ranks experiments by dollar value. The best one is an 8-week Meta pause, and I'm explicit that its power is only 38%." | Next-best-experiment card |
| 4:15–5:00 | **Real data and craft** | "Separately, on real data: a 14M-user ad experiment, and Google's GA4 store data, where I found duplicate transactions and a tracking break. Typed API, tests, accessibility checks. Every number shows where it came from." | Provenance strip + test count |

**Close:** "What I'd want to talk about is judgement: when to trust a model, and what to do when you can't."

## 15-minute technical presentation

**1. Framing (1 min).** Allocation is a causal question. Attribution, MMM and experiments answer
different questions. The goal is to grade them, not to pick a favourite.
*Speaker note:* define "incremental ROI" once, precisely: revenue that would not have happened
without the spend, per dollar.

**2. The simulator (2 min).** Geometric adstock, Hill saturation, seasonality, promotions,
channel-specific margins and repeat value. Two deliberate traps: planned budgets follow
seasonality (confounding), and brand search and retargeting spend is *caused by* demand
(reverse causation). It was pre-registered: the spec was frozen before any model was fit,
and changes are logged.
*Note:* anticipate "you rigged it": 24 randomized worlds across four regimes, including ones
built to break MMM. Its failures are published.

**3. Data engineering (2 min).** dbt-duckdb staging → intermediate → marts; a YAML metric layer
where ratios are ratios of sums; each metric is checked against an independent query. GA4: the
session key is `user_pseudo_id + ga_session_id`; first-user source is never presented as
session source (a dbt test enforces the prefix); transaction dedup rule D-011.
*Note:* show the reconciliation table in `docs/ga4-extraction.md`.

**4. Attribution (1 min).** Last-click and Markov removal effect. Both describe who touched
converters. Mean ROI error: 4.31 for last-click and 2.85 for Markov.

**5. The MMM (3 min).** Written directly in PyMC; ROI-parameterised (Meridian-style) so priors
are in business units. Variants: default priors, DAG-informed skeptical priors on harvest
channels, and calibration with a geo-lift likelihood term.
Diagnostics: R-hat, ESS, divergences, posterior predictive checks. The 13-week holdout beat
naive baselines only narrowly: 6.1% vs 6.5% and 7.1% error. Say so.
Results: mean error 1.05 → 0.46 → 0.42; coverage 89% for a nominal 90%.
*Note:* the functional forms match the simulator's, which flatters the MMM. Name this before
anyone else does.

**6. Experiments (2 min).** Geo-lift: stratified holdout regions, placebo-window standard
errors, power and minimum detectable effect. Calibration helped the tested channel in 79% of
worlds, but in the flagship world the test landed 2.9 SE from the truth and made the plan worse
(true regret $63K vs $14K).
Criteo: sample-ratio p = 0.999; intent-to-treat +27.1% visits; only 3.6% of the treated group
was exposed; the IV estimate is +28.7 pp vs a naive +37.6.

**7. Decision engine (2 min).** Exact dynamic programming on a $1K grid over 1,000 draws
(handles S-shaped curves); per-channel limits; guardrails on observed spend. Output: expected
+$55K, P10 +$8K, P90 +$108K, better than current in 94% of draws; true +$13K. Allowed to
underspend, it stops near $363K. The model is saying the budget is too large.

**8. Value of information (1 min).** Preposterior analysis: reweight the posterior draws on
simulated test outcomes, re-optimise, and measure the gain. Rank tests by net value, because
pausing an over-invested channel has *negative* cost (D-017). Perfect information about every
channel is worth at most $18.6K here.

**9. Monitoring (0:30).** Robust seasonal baseline; thresholds calibrated on incident-free
worlds; 96% recall and 66% precision out of sample across 72 incidents. Hypotheses are labelled
Confirmed / Supported / Unverified.

**10. What I got wrong (0:30).** The tie-break bug in the Qini curve; ranking tests by value of
information alone; too few posterior draws in the first scorecard. Each is fixed, with a test.

**11. Close.** With real data the scorecard becomes a design tool: it tells you which
experiments make the model trustworthy.

## More interview questions

These add to the ones in the [case study](case-study.md#5-interview-notes-likely-questions).

**Why a Normal likelihood on revenue rather than counts?** Weekly national first-order revenue
aggregates thousands of orders, so a Normal approximation on the scaled series is standard
(Meridian and PyMC-Marketing default to it). The posterior predictive checks in
`model_runs/mmm-halden-*/diagnostics.json` are the evidence to show. A count likelihood on
regional new customers would be more principled for a geo-level model and is a reasonable next step.

**Why does the optimizer use steady-state adstock?** For a flat quarterly plan, normalised
adstock converges to the weekly spend, and carryover into the quarter roughly cancels carryover
out of it. It makes response curves closed-form and fast enough for live controls. The
approximation is documented, and true regret is computed with the exact simulator.

**How do you know the anomaly precision isn't overfitted?** Thresholds were calibrated on 12
incident-free worlds and evaluated on 12 different worlds with random incidents (D-013).

**What would you change for a real company?** Geo-level hierarchical MMM (more variation, better
identification). A standing geo-holdout programme chosen by value of information. Cost data
joined in the warehouse with the same reconciliation discipline. An optional LLM layer that
rephrases the analyst's tool outputs without ever producing numbers.

**Why isn't there an LLM in the analyst?** Every number must be reproducible and cited. A
deterministic router can be tested exhaustively; one test checks that the analyst's numbers
equal the pages' numbers (D-020).
