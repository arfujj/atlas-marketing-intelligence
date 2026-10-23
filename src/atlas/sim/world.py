"""Generate a simulated geo × week marketing history with known causal truth.

Causal structure (see docs/data-generating-process.md for the DAG):

    season, trend, promos ──► baseline demand ──► new customers ──► revenue
            │                       │                  ▲
            ▼                       ▼                  │
     planned spend          demand-driven spend ───────┤  (small true effect)
     (Meta, TikTok, ...)    (brand search, retargeting)│
            └────────────── media effect ──────────────┘

The two built-in traps are deliberate and documented: planned budgets follow seasonality
(confounding), and brand search / retargeting spend is *caused by* demand rather than
causing much of it. Naive reporting and naive MMMs over-credit them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from atlas.sim.config import WorldConfig
from atlas.sim.transforms import geometric_adstock, hill

REPEAT_HORIZON_WEEKS = 52
BASELINE = "baseline"


@dataclass(frozen=True)
class SimulatedWorld:
    """Arrays are indexed [channel, geo, t] over burn-in + history; tables cover history only."""

    config: WorldConfig
    seed: int
    channels: tuple[str, ...]
    geos: tuple[str, ...]
    weeks: pd.DatetimeIndex  # full timeline incl. burn-in
    burn_in: int
    spend: np.ndarray
    adstock: np.ndarray
    half_saturation: np.ndarray  # [channel, geo]
    beta: np.ndarray  # [channel, geo], expected new customers at full saturation
    promo: np.ndarray  # [t], 0/1
    # history-only tables
    media: pd.DataFrame
    outcomes: pd.DataFrame
    calendar: pd.DataFrame
    truth_contributions: pd.DataFrame
    truth_channels: pd.DataFrame


# --------------------------------------------------------------------------- calendar


def _black_friday(year: int) -> date:
    nov1 = date(year, 11, 1)
    first_thu = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    return first_thu + timedelta(weeks=3, days=1)


def _calendar(weeks: pd.DatetimeIndex, cfg: WorldConfig, rng: np.random.Generator) -> pd.DataFrame:
    b = cfg.baseline
    starts = [d.date() for d in weeks]
    bfcm = np.array([s <= _black_friday(s.year) < s + timedelta(days=7) for s in starts])
    gifting = np.array(
        [any(date(s.year, 12, 1) <= s + timedelta(days=i) <= date(s.year, 12, 20)
             for i in range(7)) for s in starts]
    ) & ~bfcm
    promo = bfcm.copy()
    years = np.array([s.year for s in starts])
    for y in np.unique(years):
        eligible = np.flatnonzero((years == y) & ~bfcm & ~gifting)
        k = min(b.promos_per_year, eligible.size)
        promo[rng.choice(eligible, size=k, replace=False)] = True

    doy = np.array([s.timetuple().tm_yday for s in starts])
    season = np.exp(b.season_amplitude * np.cos(2 * np.pi * (doy - b.season_peak_doy) / 365.25))
    season *= (1 + b.gifting_lift * gifting) * (1 + b.bfcm_lift * bfcm)
    trend = (1 + b.annual_growth) ** (np.arange(len(weeks)) / 52.0)
    return pd.DataFrame(
        {"week_start": weeks, "season_index": season, "trend_index": trend,
         "bfcm_week": bfcm, "gifting_week": gifting, "promo_week": promo}
    )


# --------------------------------------------------------------------------- spend


def _geo_shares(rng: np.random.Generator, w: np.ndarray, t: int, vol: float) -> np.ndarray:
    raw = w[:, None] * rng.lognormal(0.0, vol, size=(w.size, t))
    return raw / raw.sum(axis=0, keepdims=True)


def _pulse(rng: np.random.Generator, t: int, on: int = 6, off: int = 3) -> np.ndarray:
    phase = rng.integers(0, on + off)
    pattern = ((np.arange(t) + phase) % (on + off)) < on
    return pattern * (on + off) / on  # mean-preserving


def _scale_to_budget(
    raw: np.ndarray, annual: float, burn: int, active_hist_weeks: int
) -> np.ndarray:
    hist_total = raw[:, burn:].sum()
    target = annual * active_hist_weeks / 52.0
    return raw * (target / hist_total)


# --------------------------------------------------------------------------- simulate


def simulate(cfg: WorldConfig, seed: int = 20261023) -> SimulatedWorld:
    rng = np.random.default_rng(seed)
    b = cfg.baseline
    burn, n = cfg.burn_in_weeks, cfg.n_weeks
    T, G = burn + n, cfg.n_geos
    w = np.asarray(cfg.geo_weights)
    weeks = pd.date_range(cfg.history_start - timedelta(weeks=burn), periods=T, freq="7D")
    geos = tuple(f"R{g + 1:02d}" for g in range(G))
    chans = cfg.channels
    C = len(chans)

    cal = _calendar(weeks, cfg, rng)
    promo = cal["promo_week"].to_numpy(dtype=float)
    season, trend = cal["season_index"].to_numpy(), cal["trend_index"].to_numpy()
    disc = b.promo_discount * promo  # [t]

    # Baseline (non-paid) demand with slowly varying geo-level shocks.
    shocks = np.zeros((G, T))
    eps = rng.normal(0, 0.04, size=(G, T))
    for t in range(T):
        shocks[:, t] = (0.7 * shocks[:, t - 1] if t else 0) + eps[:, t]
    base_new = (b.new_customers_weekly * w[:, None] * trend * season
                * (1 + b.promo_lift * promo) * np.exp(shocks))

    spend = np.zeros((C, G, T))
    ads = np.zeros((C, G, T))
    K = np.zeros((C, G))
    beta = np.zeros((C, G))
    contrib = np.zeros((C, G, T))
    active = np.zeros((C, T), dtype=bool)

    def _fit_channel(i: int) -> None:
        c = chans[i]
        ads[i] = geometric_adstock(spend[i], c.adstock_decay)
        hist = np.s_[burn + c.launch_week:]
        K[i] = c.half_sat_ratio * ads[i][:, hist].mean(axis=1)
        sat = hill(ads[i], K[i][:, None], c.hill_slope)
        # Calibrate so realised expected first-order ROI over history equals target_roi.
        rev_per_unit = (w[:, None] * sat * c.first_order_aov * (1 - disc))[:, burn:].sum()
        b_c = c.target_roi * spend[i][:, burn:].sum() / rev_per_unit
        beta[i] = b_c * w
        contrib[i] = beta[i][:, None] * sat

    # 1) planned channels: budgets follow trend and (tilted) seasonality → confounding.
    for i, c in enumerate(chans):
        active[i] = np.arange(T) >= burn + c.launch_week
        if c.spend_policy != "planned":
            continue
        nat = trend * season**c.seasonal_tilt * rng.lognormal(0, c.weekly_volatility, T)
        if c.flighting == "pulsed":
            nat = nat * _pulse(rng, T)
        raw = nat * _geo_shares(rng, w, T, cfg.geo_share_volatility) * active[i]
        spend[i] = _scale_to_budget(raw, c.annual_spend, burn, n - c.launch_week)
        _fit_channel(i)

    # 2) demand-driven channels: spend responds to total demand (baseline + planned media).
    demand = base_new + contrib.sum(axis=0)
    for i, c in enumerate(chans):
        if c.spend_policy != "demand_driven":
            continue
        lagged = np.roll(demand, c.demand_lag_weeks, axis=1)
        lagged[:, : c.demand_lag_weeks] = demand[:, :1]
        raw = lagged * rng.lognormal(0, c.weekly_volatility, (G, T)) * active[i]
        spend[i] = _scale_to_budget(raw, c.annual_spend, burn, n - c.launch_week)
        _fit_channel(i)

    # 3) outcomes. Truth is the *expected* split by source; realised counts carry noise.
    sources = (BASELINE, *[c.name for c in chans])
    mean_by_src = np.concatenate([base_new[None], contrib])  # [S, G, T]
    mean_total = mean_by_src.sum(axis=0)
    r = b.nb_dispersion
    new_customers = rng.negative_binomial(r, r / (r + mean_total)).astype(float)
    share = mean_by_src / mean_total
    acquired = share * new_customers  # [S, G, T]

    aov = np.array([b.first_order_aov, *[c.first_order_aov for c in chans]])[:, None, None]
    cm = np.array([b.first_order_cm_rate, *[c.first_order_cm_rate for c in chans]])[:, None, None]
    rep = np.array([b.repeat_revenue_52w, *[c.repeat_revenue_52w for c in chans]])[:, None, None]
    aov_noise = rng.lognormal(0, b.aov_noise_sd, (G, T))
    first_rev = (acquired * aov * (1 - disc)).sum(axis=0) * aov_noise
    first_cm = (acquired * aov * (cm - disc)).sum(axis=0) * aov_noise

    kern = np.exp(-np.arange(REPEAT_HORIZON_WEEKS) / b.repeat_decay_weeks)
    kern /= kern.sum()
    repeat_list = np.zeros((G, T))
    acq_value = (acquired * rep).sum(axis=0)  # [G, T] expected 52w repeat revenue acquired at t
    for j in range(1, REPEAT_HORIZON_WEEKS + 1):
        repeat_list[:, j:] += acq_value[:, :-j] * kern[j - 1]
    repeat_list *= rng.lognormal(0, 0.04, (G, T))
    repeat_rev = repeat_list * (1 - disc)
    repeat_cm = repeat_list * (b.repeat_cm_rate - disc)

    # ------------------------------------------------------------------ tables (history)
    H = np.s_[burn:]
    hist_weeks = weeks[burn:]
    gg, tt = np.meshgrid(np.arange(G), np.arange(n), indexing="ij")

    def _frame(**cols: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(
            {"week_start": hist_weeks[tt.ravel()], "geo": np.array(geos)[gg.ravel()],
             **{k: v.ravel() for k, v in cols.items()}}
        )

    media_parts = []
    for i, c in enumerate(chans):
        s = spend[i][:, H]
        imps = np.round(s / c.cpm * 1000 * rng.lognormal(0, 0.05, s.shape))
        clicks = np.round(imps * c.ctr * rng.lognormal(0, 0.05, s.shape))
        media_parts.append(
            _frame(spend=s, impressions=imps, clicks=clicks).assign(channel=c.name)
        )
    media = pd.concat(media_parts, ignore_index=True)[
        ["week_start", "geo", "channel", "spend", "impressions", "clicks"]
    ]

    outcomes = _frame(
        new_customers=new_customers[:, H],
        first_order_revenue=first_rev[:, H],
        first_order_contribution=first_cm[:, H],
        repeat_revenue=repeat_rev[:, H],
        repeat_contribution=repeat_cm[:, H],
    )
    outcomes["revenue"] = outcomes.first_order_revenue + outcomes.repeat_revenue
    outcomes["orders"] = outcomes.new_customers + np.round(
        repeat_list[:, H].ravel() / b.repeat_aov
    )

    truth_parts = []
    for s_idx, name in enumerate(sources):
        m = mean_by_src[s_idx][:, H]
        d = disc[None, H]
        truth_parts.append(
            _frame(
                expected_new_customers=m,
                first_order_revenue=m * aov[s_idx, 0, 0] * (1 - d),
                first_order_contribution=m * aov[s_idx, 0, 0] * (cm[s_idx, 0, 0] - d),
                ltv52_revenue=m * rep[s_idx, 0, 0],
                ltv52_contribution=m * rep[s_idx, 0, 0] * b.repeat_cm_rate,
            ).assign(source=name)
        )
    truth_contributions = pd.concat(truth_parts, ignore_index=True)

    rows = []
    for i, c in enumerate(chans):
        sp = spend[i][:, H].sum()
        tc = truth_contributions[truth_contributions.source == c.name]
        rows.append({
            "channel": c.name, "label": c.label, "spend_policy": c.spend_policy,
            "history_spend": sp,
            "true_roi_first_order": tc.first_order_revenue.sum() / sp,
            "true_roi_ltv52": (tc.first_order_revenue.sum() + tc.ltv52_revenue.sum()) / sp,
            "true_profit_roi_first_order": tc.first_order_contribution.sum() / sp,
            "true_profit_roi_ltv52": (tc.first_order_contribution.sum()
                                      + tc.ltv52_contribution.sum()) / sp,
            "adstock_decay": c.adstock_decay, "hill_slope": c.hill_slope,
            "half_sat_ratio": c.half_sat_ratio,
        })
    truth_channels = pd.DataFrame(rows)

    return SimulatedWorld(
        config=cfg, seed=seed, channels=tuple(c.name for c in chans), geos=geos,
        weeks=weeks, burn_in=burn, spend=spend, adstock=ads, half_saturation=K,
        beta=beta, promo=promo, media=media, outcomes=outcomes,
        calendar=cal.iloc[burn:].reset_index(drop=True),
        truth_contributions=truth_contributions, truth_channels=truth_channels,
    )
