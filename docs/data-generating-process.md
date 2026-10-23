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
   Seed 20261023, naive OLS with no controls: brand search **$17.8 of revenue per $1**
   (true $0.50), retargeting **$9.4** (true $0.70), TikTok **−$0.02** (true $2.80).
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

## 6. Known simplifications (documented limitations)

- Media effects are constant over time and additive across channels (no synergy).
- No competitor activity, no price elasticity beyond promotions, no supply constraints.
- Repeat value is truncated at 52 weeks.
- One world is a single draw. Phase 2 grades every method across ≥ 20 worlds with
  randomised parameters, including worlds designed so that MMM *should* fail.

## Changelog

- 2026-10-23: v0.1. Baseline organic demand lowered from 1000 to 780 new customers per week before any model was fit (MER 7.9 → 6.9, closer to typical DTC levels).
