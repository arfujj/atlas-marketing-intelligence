# Case study: grading marketing measurement against a known truth

*All figures come from committed runs under `model_runs/`; run ids are given where a number is
quoted. Halden numbers are simulated; GA4 and Criteo numbers are observed.*

## 1. The question

A coffee brand has $500K for next quarter's paid media across six channels. Which allocation
maximises profit, how sure can we be, and what should we test before committing?

No public dataset can answer this honestly: real data never reveals true incremental ROI. So the
question is asked inside a simulated company whose causal truth was written down first
([data-generating process](data-generating-process.md)), and the methods that would be used on
real data are graded against that truth. Real datasets are used for what they *can* support,
in separate workspaces.

## 2. Approach

| Step | What | Why |
|---|---|---|
| Simulate | 156 weeks × 10 regions × 6 channels; adstock, saturation, seasonality, promotions, demand-driven brand search, customer journeys, injected incidents | Known truth, with the confounding that makes real measurement hard |
| Attribute | Last-click and Markov removal-effect attribution on simulated journeys | The numbers most teams actually look at |
| Model | Bayesian MMM in PyMC: default priors, DAG-informed priors, and calibrated with a geo-lift | Separates "MMM" from "MMM with the right assumptions" |
| Experiment | Stratified geo-holdout with placebo-window standard errors; power and MDE per design | What a team could actually run next quarter |
| Decide | Exact optimisation over 1,000 posterior draws, per-channel limits, observed-range guardrails, sensitivity tornado | Uncertainty as an input, not a footnote |
| Value of information | Expected value of sample information for each candidate test, net of its expected cost | "Which experiment is worth running?" as a dollar figure |
| Grade | Everything repeated in 24 randomized worlds across four regimes | One world is an anecdote |

## 3. Findings

**Attribution is credit, not causation.** In the flagship world, last-click puts brand search at
$18.96 of revenue per dollar and retargeting at $5.40. Their true incremental returns are $0.50
and $0.70: those channels mostly collect demand other channels created. Across 24 worlds,
last-click's mean ROI error is 4.31; plans built on it do worse than the current plan in 83% of
worlds (`scorecard-24w-9a760623`).

**An MMM is only as good as its priors.** With default priors, brand search still looks strong
(3.9 in the flagship world): its spend follows demand, so the model credits it with sales it did
not cause. Encoding that structure — skeptical priors on harvest channels — cuts the mean error
from 1.05 to 0.46 across worlds.

**One experiment helps on average and can mislead in any single case.** Calibrating with one
geo-lift cut the tested channel's error from 0.63 to 0.45 on average and improved it in 79% of
worlds. In the flagship world, though, the go-dark test on Meta prospecting measured +$3.9K
against a true −$48K, 2.9 standard errors away, and the calibrated plan was worse than the
uncalibrated one (true regret $63K vs $14K). Two of the 24 worlds produced a calibrated plan
worse than the current plan. These are reported, not filtered.

**The $500K decision.** The calibrated model recommends cutting Meta prospecting, retargeting and
brand search and moving the money into non-brand search and TikTok: expected 52-week profit
+$55K (P10 +$8K, P90 +$108K; better in 94% of posterior draws). Graded against the truth, the
plan earns +$13K over the current plan — positive, but well below the model's expectation. The
model also flags that the budget exceeds what it can spend profitably: allowed to underspend, it
would stop at about $363K.

**Which test next.** Ranked by net value, the best candidate is an 8-week Meta prospecting go-dark
in two regions per stratum. Most of its value is the spend saved while paused; its power at the
predicted effect is 38%, so a null result should be read as inconclusive. Perfect information
about every channel would be worth at most $18.6K for this decision.

**Monitoring.** The change detector (robust seasonal baseline, thresholds calibrated on
incident-free worlds) finds 96% of 72 injected incidents in 12 held-out worlds, with 66% of
alerts real (`anomaly-20261023-d6a9f4ff`). Each flagged week gets ranked hypotheses tagged
Confirmed (arithmetic decomposition), Supported hypothesis or Unverified.

**GA4 (observed).** Deduplicated revenue is $307,640, not the naive $362,165: 335 purchase rows
repeat an already-seen transaction id, and 906 have no usable id. The late-January drop is a
tracking failure: purchase events per 1,000 sessions are unchanged (12.4 → 12.6) while the
share of purchases with a transaction id falls from 92% to 18%.

**Criteo (observed RCT, 13.98M users).** Assignment to ads raised visits by 27.1% (95% CI
26.2–28.0%) and conversions by 59.4% (54.4–64.7%). Only 3.6% of the treated group was actually
exposed; using assignment as an instrument, the effect on exposed users is +28.7 percentage
points of visit rate, while the naive exposed-vs-control comparison overstates it at +37.6.
Uplift models rank users usefully on held-out data (Qini 0.0033 vs −0.0001 for random).

## 4. What I got wrong along the way

- **A ranking bug understated a model by 35%.** Tied uplift scores kept file order, which was
  grouped by treatment, bending the X-learner's Qini curve. Found by looking at the chart; fixed
  with random tie-breaking and a regression test (decision D-016).
- **The first "next best experiment" ranked by information value alone** and recommended a test
  that loses $12K. Pausing an over-invested channel has *negative* cost, so net value is the right
  ranking (D-017).
- **The first multi-world run used too few posterior draws**; most fits failed the convergence
  bar. The results looked similar, but numbers from unconverged fits are not defensible, so the
  run was repeated with the flagship settings (D-015).
- **The change detector double-explained a site-wide outage** as regional tracking failures too.
  Fixed so one cause gets one explanation (D-014).

## 5. Interview notes: likely questions

**Why trust your MMM?** I don't, by default. I trust it where it has been checked: convergence
diagnostics, a 13-week holdout against naive baselines (6.1% error vs 6.5% and 7.1% — a narrow win), ROI recovery in 24 worlds, and
interval coverage (89% for a nominal 90%). The scorecard is generous to it because its functional
forms match the simulator's; mismatched-form runs are the next robustness check.

**How did you treat brand search?** As a harvest channel: spend responds to demand, so it is
confounded with sales. The DAG-informed variant puts a skeptical prior on its ROI. That single
choice is the biggest difference between the default and the DAG-informed model.

**Why not Markov or Shapley attribution?** They distribute credit among touchpoints more cleverly
than last-click but still answer "who touched the converter", not "what would have happened
without the ad". In the scorecard Markov's mean error is 2.85 — better than last-click, far from
causal.

**What are the CI and power on the Criteo lift?** Visits +27.1% (26.2–28.0%), conversions +59.4%
(54.4–64.7%); the minimum detectable relative lift at 80% power is 1.1% for visits and 4.8% for
conversions, so the test is heavily over-powered for the average effect.

**What would change with a real company's data?** No truth to grade against, so the scorecard
becomes a design tool: it tells you which experiments to run to make the MMM trustworthy. The
pipeline (metric layer, evidence labels, optimizer over posterior draws, value of information) is
unchanged.

**Why not recommend the optimizer's plan outright?** Because the value of information is low and
the gain is uncertain (P10 +$8K): the honest recommendation is the plan *plus* the go-dark test,
and to revisit the budget level, since the model sees the last ~$137K as unprofitable.
