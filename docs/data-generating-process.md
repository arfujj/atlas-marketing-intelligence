# Halden Coffee Works — Data-Generating Process (pre-registered)

> **SYNTHETIC.** Halden Coffee Works is a fictional company. Every parameter below is an
> assumption chosen to create a realistic *measurement problem*, not a description of any
> real business. This document is frozen before any attribution or MMM is fit; changes after
> that point must be logged in the changelog at the bottom with a reason.

Source of truth: `src/atlas/sim/config.py` (`default_world()`), `src/atlas/sim/world.py`.
Every output carries `manifest.json` with `seed` and `config_fingerprint`.

## 1. Business

DTC specialty coffee: whole-bean bags (high repeat, ~48% contribution margin) and brewing
equipment (high AOV, low repeat, ~28% margin). Channel mix determines product mix, so
**first-order AOV, margin and 52-week repeat value differ by acquisition channel**: the
revenue-maximising and profit-maximising allocations are different by design.

| | Value (seed 20261023) |
|---|---|
| History | 156 weeks, 2023-10-02 → 2026-09-21, 10 regions (R01–R10) |
| Revenue | ≈ $12.6M / yr (≈ 47% from repeat orders) |
| Paid media | ≈ $1.84M / yr across 6 channels (≈ $478K per quarter — the $500K question is +5%) |
| MER | ≈ 6.9 |
| Paid share of new customers (true, expected) | ≈ 49% |

## 2. Causal structure

```
 season, trend ─┬──────────────► baseline new customers ─┬─► new customers ─► first-order revenue
 promos ────────┘                        │               │          │
        │                                ▼               │          └─► repeat revenue (52-week kernel)
        ▼                       demand-driven spend      │
  planned spend ──► adstock ──► Hill saturation ─────────┘
  (non-brand search, Meta prospecting, TikTok, YouTube)
                    demand-driven spend ──► adstock ──► Hill ──► (small true effect)
                    (brand search: same week; retargeting: 1-week lag)
```

Deliberate measurement traps (each is something real marketing data does):

1. **Seasonal confounding.** Planned budgets scale with `season^tilt × trend`. Spend is high
   when demand is high anyway. A model without seasonality/trend controls over-credits media.
2. **Reverse causation in harvest channels.** Brand-search and retargeting spend are *driven by*
   total demand (baseline + other media). Their true ROI is low (0.5, 0.7), but their spend is
   highly correlated with revenue (`corr > 0.8`, tested).
   Seed 20261023, naive OLS of national weekly first-order revenue on spend with no controls:
   brand search **$17.8 of revenue per $1** (true $0.50), retargeting **$9.3** (true $0.70),
   TikTok **−$0.03** (true $2.80). (v0.1 without incidents: $17.81 / $9.41 / −$0.02.)
3. **Short-history channel.** TikTok launches at week 40, so it has ~116 weeks of data and a wide
   range of spend. It is the channel furthest from saturation.
4. **Long carryover.** YouTube has adstock decay 0.6 and pulsed flighting (6 weeks on, 3 off).
5. **Long-term value outside the MMM target.** Repeat revenue arrives over 52 weeks after
   acquisition. An MMM on weekly revenue absorbs most of this into baseline/trend.

## 3. Equations (per channel c, geo g, week t)

- Adstock: `a[t] = x[t] + λ_c · a[t-1]` (unnormalised).
- Saturation: `h(a) = a^s / (a^s + K^s)`, with `K_cg = half_sat_ratio_c × mean_t a_cg[t]`.
- Expected incremental new customers: `μ_cgt = β_c · w_g · h(a_cgt)`.
  `β_c` is solved so that the expected first-order revenue ROI over the history equals
  `target_roi_c` exactly (unit-tested).
- Baseline: `B_gt = 780 · w_g · trend_t · season_t · (1 + 0.20·promo_t) · exp(AR1 shock_gt)`.
- Observed new customers: `NegBin(mean = B + Σ_c μ, dispersion = 40)`.
- Promotions (Black Friday/Cyber Monday week plus 4 random weeks per year): 15% discount, which
  lowers both revenue and contribution: `contribution = list_revenue × (cm − d)`.
- Repeat revenue: acquired customers × channel-specific 52-week value × exponential kernel (τ = 18 weeks).

## 4. True channel economics (seed 20261023, at current quarterly spend)

| Channel | Avg ROI (1st-order rev) | Marginal ROI (rev) | Marginal contribution (1st order) | Marginal contribution (incl. 52-week repeat) |
|---|---|---|---|---|
| Search · Non-brand | 2.00 | 1.32 | 0.48 | 0.95 |
| Search · Brand | 0.50 | 0.17 | 0.07 | 0.16 |
| Meta · Prospecting | 2.20 | 1.53 | 0.61 | 1.26 |
| Meta · Retargeting | 0.70 | 0.28 | 0.11 | 0.24 |
| TikTok | 2.80 | 2.79 | 1.17 | 2.05 |
| YouTube | 1.40 | 1.27 | 0.41 | 0.72 |

A marginal contribution below 1.0 means the next dollar loses money on that basis.

**These are the answers the analyst is *not* allowed to see.** They live only in
`data/synthetic/halden/truth/` and are used to grade methods, never to fit them.

## 5. What is observable vs hidden

| Observable (`observed/`) | Hidden (`truth/`) |
|---|---|
| spend, impressions, clicks by channel × geo × week | adstock, saturation, β, K |
| new customers, orders, revenue, contribution by geo × week | expected contribution by source |
| promo / BFCM / gifting week flags | latent season & trend indices |
| site sessions (paid = clicks, organic/direct) by geo × week | — |
| customer journeys (touch paths, converted flag, weight) | causal source of each converting journey |
| — | injected incidents (`truth/incidents.parquet`) |

## 5b. v0.2 extensions (added before any model was fit)

**Site sessions.** Paid sessions equal platform clicks. Organic/direct sessions =
`80 × expected baseline new customers + 10 × repeat orders`, each with 5% lognormal noise.
Conversion rate = orders / sessions ≈ 3.2% (seed 20261023). Sessions are *observed*; they are
deliberately **not** used as an MMM control (see docs/decisions.md D-008).

**Incidents** (operational or measurement; none changes a true media effect; truth in
`truth/incidents.parquet`). Scheduled in the last 20 history weeks of the Halden world:

| id | kind | week (index / start) | scope | effect |
|---|---|---|---|---|
| INC01 | tracking outage | 140 / 2026-06-08 | R03 | recorded new customers, orders, revenue, contribution −55%; sessions and clicks normal |
| INC02 | CPC spike | 146–149 / 2026-07-20 → 2026-08-10 | Search · Non-brand, all regions | billed spend +40%; impressions, clicks and true effect unchanged (the extra spend buys nothing) |
| INC03 | checkout incident | 155 / 2026-09-21 (final week) | all regions | real loss: realised new customers binomially thinned by 20% (they never generate repeat), repeat orders −20%; sessions normal |

`incident_mode="random"` (used by `sample_world`) draws `n_random_incidents` (default 6)
non-overlapping incidents on a 6-week lattice in the last 52 weeks: tracking outage (one
region, −30% to −70%), CPC spike (2–5 weeks, +25% to +60%, one of non-brand search, brand
search, Meta prospecting, TikTok) or checkout incident (−10% to −30%).

**Customer journeys** (`observed/journeys.parquet`, one row per journey, path as
`ch1>ch2>…`). Every recorded new customer gets one converting journey. Its causal source is
drawn from the true expected source shares of that geo-week (truth:
`truth/journey_sources.parquet`). Path length is `1 + Poisson(1.6)`. Touches are drawn from the
six paid channels in proportion to that geo-week's clicks and from organic search / direct in
proportion to organic sessions (×0.25: most organic visits are not tracked marketing touches).
If the source is a paid channel it is inserted before the last position when absent. Then,
**independently of the causal source**, with probability 0.6 the last touch is replaced by a
harvest channel (brand search or retargeting, split by clicks); if that would delete the
causal touch, the harvest touch is appended instead. Result (seed 20261023): brand search is
the last touch on 54% of converting journeys but the causal source of 1.3%; retargeting 15%
vs 2.0%. Non-converting journeys (2 per converter, weight 25 each, length `1 + Poisson(1)`,
harvest last-touch probability 0.24) are included for Markov attribution.

## 6. Known simplifications (documented limitations)

- Media effects are constant over time and additive across channels (no synergy).
- No competitor activity, no price elasticity beyond promotions, no supply constraints.
- Repeat value is truncated at 52 weeks.
- One world is a single draw. Phase 2 grades every method across ≥ 20 worlds with
  randomised parameters, including worlds designed so that MMM *should* fail.

## 7. Randomised worlds (`sample_world(seed)`, multi-world evaluation)

Each world perturbs the Halden template. Regime drawn with probabilities standard 0.55,
collinear 0.15, weak_signal 0.15, long_carryover 0.15.

| Parameter | Range |
|---|---|
| target ROI, planned channels | log-uniform 0.6–3.5 (weak_signal: 0.3–1.75) |
| target ROI, harvest channels | log-uniform 0.2–1.2 (weak_signal: 0.1–0.6) |
| adstock decay | planned U(0, 0.6) (long_carryover: U(0, 0.8)); harvest U(0, 0.3) |
| Hill half-saturation ratio / slope | U(0.5, 2.5) / U(0.8, 2.0) |
| annual spend | Halden × U(0.6, 1.5) (weak_signal × 0.6) |
| seasonal tilt / weekly volatility (planned) | U(0, 1.2) / U(0.08, 0.35); collinear: shared tilt U(1.0, 1.4) ± 5%, volatility U(0.02, 0.06), geo-share volatility 0.03 |
| TikTok launch week | 0–80 |
| first-order AOV, CM rate, 52-week repeat value | × U(0.8, 1.2), × U(0.85, 1.15), × U(0.7, 1.3) |
| baseline new customers / week | U(600, 1000) |

Collinear worlds are where an MMM on national data *should* fail to separate channels.

## Changelog

- 2026-10-23: v0.1. Baseline organic demand lowered from 1000 to 780 new customers per week before any model was fit (MER 7.9 → 6.9, closer to typical DTC levels).
- 2026-10-23: v0.2, before any attribution or MMM was fit. Added site sessions, three scheduled
  incidents (plus a seeded random-incident mode), customer journeys and `sample_world`.
  Reason: conversion rate, anomaly-detector evaluation and attribution all need these
  inputs. New components use independent child RNG streams (`[seed, 101/202/303]`), so all
  v0.1 draws are unchanged; with incidents disabled the v0.1 tables are reproduced exactly
  (naive-OLS brand search $17.81/$ in both). The incidents change observed values only as
  documented in §5b. Media `spend` is now *billed* spend; true effects are driven by effective
  spend (identical except during INC02). `truth/channels.parquet` adds
  `true_roi_first_order_billed`, which is what methods are graded against.
