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

v0.2 adds site sessions, operational/measurement incidents and customer journeys. They use
independent child RNG streams, so the v0.1 draws are unchanged except where an incident
deliberately alters a recorded value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from atlas.sim.config import IncidentSpec, WorldConfig
from atlas.sim.transforms import geometric_adstock, hill

REPEAT_HORIZON_WEEKS = 52
BASELINE = "baseline"
ORGANIC_TOUCHES = ("organic_search", "direct")
HARVEST = ("search_brand", "meta_retargeting")
CPC_SPIKE_CHANNELS = ("search_nonbrand", "search_brand", "meta_prospecting", "tiktok")
INCIDENT_EFFECTS = {
    "tracking_outage": "recorded orders, new customers and revenue fall; sessions and clicks "
                       "normal; no real business loss (measurement)",
    "cpc_spike": "billed spend rises with unchanged impressions, clicks and true effect; the "
                 "extra spend buys nothing",
    "checkout_incident": "real loss: new customers, orders and revenue fall site-wide; "
                         "sessions and clicks normal",
}


@dataclass(frozen=True)
class SimulatedWorld:
    """Arrays are indexed [channel, geo, t] over burn-in + history; tables cover history only."""

    config: WorldConfig
    seed: int
    channels: tuple[str, ...]
    geos: tuple[str, ...]
    weeks: pd.DatetimeIndex  # full timeline incl. burn-in
    burn_in: int
    spend: np.ndarray  # effective spend: what buys media and drives true effects
    billed_spend: np.ndarray  # what platforms invoiced (differs during a CPC spike)
    adstock: np.ndarray
    half_saturation: np.ndarray  # [channel, geo]
    beta: np.ndarray  # [channel, geo], expected new customers at full saturation
    promo: np.ndarray  # [t], 0/1
    # history-only tables
    media: pd.DataFrame
    outcomes: pd.DataFrame
    calendar: pd.DataFrame
    sessions: pd.DataFrame
    truth_contributions: pd.DataFrame
    truth_channels: pd.DataFrame
    incidents: pd.DataFrame  # truth: injected incidents
    journeys: pd.DataFrame | None  # observed customer journeys (attribution input)
    journey_sources: pd.DataFrame | None  # truth: causal source of each converting journey


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


# --------------------------------------------------------------------------- incidents


def resolve_incidents(cfg: WorldConfig, rng: np.random.Generator) -> tuple[IncidentSpec, ...]:
    """Scheduled incidents from the config, seeded random ones, or none."""
    if cfg.incident_mode == "none":
        return ()
    if cfg.incident_mode == "scheduled":
        return cfg.incidents
    names = [c.name for c in cfg.channels]
    chans = [c for c in CPC_SPIKE_CHANNELS if c in names] or names
    win = min(cfg.random_incident_window_weeks, cfg.n_weeks - 6)
    # Starts on a 6-week lattice so incidents never overlap (keeps evaluation unambiguous).
    lattice = np.arange(cfg.n_weeks - win, cfg.n_weeks - 5, 6)
    k = min(cfg.n_random_incidents, lattice.size)
    starts = np.sort(rng.choice(lattice, size=k, replace=False))
    out = []
    for start in starts:
        kind = str(rng.choice(["tracking_outage", "cpc_spike", "checkout_incident"]))
        if kind == "tracking_outage":
            out.append(IncidentSpec(kind=kind, start_week=int(start),
                                    geo=f"R{rng.integers(1, cfg.n_geos + 1):02d}",
                                    magnitude=float(rng.uniform(0.3, 0.7))))
        elif kind == "cpc_spike":
            out.append(IncidentSpec(kind=kind, start_week=int(start),
                                    n_weeks=int(rng.integers(2, 6)),
                                    channel=str(rng.choice(chans)),
                                    magnitude=float(rng.uniform(0.25, 0.6))))
        else:
            out.append(IncidentSpec(kind=kind, start_week=int(start),
                                    magnitude=float(rng.uniform(0.1, 0.3))))
    return tuple(out)


def incidents_frame(incidents: tuple[IncidentSpec, ...],
                    hist_weeks: pd.DatetimeIndex) -> pd.DataFrame:
    cols = ["incident_id", "kind", "start_week", "end_week", "n_weeks", "geo", "channel",
            "magnitude", "real_business_loss", "changes_true_media_effect", "effect"]
    rows = [{
        "incident_id": f"INC{k + 1:02d}", "kind": inc.kind,
        "start_week": hist_weeks[inc.start_week],
        "end_week": hist_weeks[inc.start_week + inc.n_weeks - 1],
        "n_weeks": inc.n_weeks, "geo": inc.geo or "ALL", "channel": inc.channel or "",
        "magnitude": inc.magnitude, "real_business_loss": inc.kind == "checkout_incident",
        "changes_true_media_effect": False, "effect": INCIDENT_EFFECTS[inc.kind],
    } for k, inc in enumerate(incidents)]
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------- simulate


def simulate(cfg: WorldConfig, seed: int = 20261023, journeys: bool = True) -> SimulatedWorld:
    rng = np.random.default_rng(seed)
    rng_inc = np.random.default_rng([seed, 101])
    rng_ses = np.random.default_rng([seed, 202])
    rng_path = np.random.default_rng([seed, 303])
    b = cfg.baseline
    burn, n = cfg.burn_in_weeks, cfg.n_weeks
    T, G = burn + n, cfg.n_geos
    w = np.asarray(cfg.geo_weights)
    weeks = pd.date_range(cfg.history_start - timedelta(weeks=burn), periods=T, freq="7D")
    geos = tuple(f"R{g + 1:02d}" for g in range(G))
    chans = cfg.channels
    names = [c.name for c in chans]
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
    sources = (BASELINE, *names)
    mean_by_src = np.concatenate([base_new[None], contrib])  # [S, G, T]
    mean_total = mean_by_src.sum(axis=0)
    r = b.nb_dispersion
    new_customers = rng.negative_binomial(r, r / (r + mean_total)).astype(float)

    # Incidents. A checkout failure is a real loss (customers and repeat orders are thinned);
    # a CPC spike inflates billed spend only; a tracking outage changes *recorded* outcomes.
    incidents = resolve_incidents(cfg, rng_inc)
    real_keep = np.ones((G, T))
    rec_keep = np.ones((G, T))
    billed = spend.copy()
    gi = {g: k for k, g in enumerate(geos)}
    for inc in incidents:
        sl = slice(burn + inc.start_week, burn + inc.start_week + inc.n_weeks)
        rows = slice(None) if inc.geo is None else gi[inc.geo]
        if inc.kind == "checkout_incident":
            real_keep[rows, sl] *= 1 - inc.magnitude
        elif inc.kind == "tracking_outage":
            rec_keep[rows, sl] *= 1 - inc.magnitude
        else:
            billed[names.index(inc.channel), rows, sl] *= 1 + inc.magnitude
    lost = real_keep < 1
    if lost.any():
        new_customers[lost] = rng_inc.binomial(
            new_customers[lost].astype(np.int64), real_keep[lost]).astype(float)

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
    visiting_repeat = np.round(repeat_list / b.repeat_aov)  # visits happen regardless
    repeat_list *= real_keep
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
        s = spend[i][:, H]  # impressions and clicks are bought by *effective* spend
        imps = np.round(s / c.cpm * 1000 * rng.lognormal(0, 0.05, s.shape))
        clicks = np.round(imps * c.ctr * rng.lognormal(0, 0.05, s.shape))
        media_parts.append(
            _frame(spend=billed[i][:, H], impressions=imps, clicks=clicks).assign(channel=c.name)
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
    repeat_orders = np.round(repeat_list / b.repeat_aov)
    outcomes["orders"] = outcomes.new_customers + repeat_orders[:, H].ravel()
    # Tracking outage: the purchase tag under-records orders and revenue (not sessions).
    rk = rec_keep[:, H].ravel()
    if (rk < 1).any():
        for col in ("first_order_revenue", "first_order_contribution", "repeat_revenue",
                    "repeat_contribution"):
            outcomes[col] = outcomes[col] * rk
        outcomes["new_customers"] = np.round(outcomes.new_customers * rk)
        outcomes["orders"] = np.round(outcomes.orders * rk)
    outcomes["revenue"] = outcomes.first_order_revenue + outcomes.repeat_revenue
    outcomes = outcomes[["week_start", "geo", "new_customers", "orders", "revenue",
                         "first_order_revenue", "first_order_contribution", "repeat_revenue",
                         "repeat_contribution"]]

    # Site sessions: paid sessions = platform clicks; organic/direct sessions scale with
    # baseline (non-paid) demand and with repeat-order activity.
    paid = media.groupby(["geo", "week_start"]).clicks.sum()
    organic = (cfg.organic_sessions_per_baseline_customer * base_new
               * rng_ses.lognormal(0, 0.05, (G, T))
               + cfg.sessions_per_repeat_order * visiting_repeat
               * rng_ses.lognormal(0, 0.05, (G, T)))
    sessions = _frame(organic_direct_sessions=np.round(organic[:, H]))
    idx = pd.MultiIndex.from_arrays([sessions.geo, sessions.week_start])
    sessions["paid_sessions"] = paid.reindex(idx).to_numpy()
    sessions["sessions"] = sessions.organic_direct_sessions + sessions.paid_sessions

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
        bl = billed[i][:, H].sum()
        tc = truth_contributions[truth_contributions.source == c.name]
        rows.append({
            "channel": c.name, "label": c.label, "spend_policy": c.spend_policy,
            "history_spend": sp,
            "billed_spend": bl,
            "true_roi_first_order": tc.first_order_revenue.sum() / sp,
            "true_roi_first_order_billed": tc.first_order_revenue.sum() / bl,
            "true_roi_ltv52": (tc.first_order_revenue.sum() + tc.ltv52_revenue.sum()) / sp,
            "true_profit_roi_first_order": tc.first_order_contribution.sum() / sp,
            "true_profit_roi_ltv52": (tc.first_order_contribution.sum()
                                      + tc.ltv52_contribution.sum()) / sp,
            "adstock_decay": c.adstock_decay, "hill_slope": c.hill_slope,
            "half_sat_ratio": c.half_sat_ratio,
        })
    truth_channels = pd.DataFrame(rows)

    jr = js = None
    if journeys:
        jr, js = _journeys(cfg, rng_path, media, sessions, outcomes,
                           share[:, :, H], sources, names)

    return SimulatedWorld(
        config=cfg, seed=seed, channels=tuple(names), geos=geos,
        weeks=weeks, burn_in=burn, spend=spend, billed_spend=billed, adstock=ads,
        half_saturation=K, beta=beta, promo=promo, media=media, outcomes=outcomes,
        calendar=cal.iloc[burn:].reset_index(drop=True), sessions=sessions,
        truth_contributions=truth_contributions, truth_channels=truth_channels,
        incidents=incidents_frame(incidents, hist_weeks), journeys=jr, journey_sources=js,
    )


# --------------------------------------------------------------------------- journeys


def _journeys(cfg: WorldConfig, rng: np.random.Generator, media: pd.DataFrame,
              sessions: pd.DataFrame, outcomes: pd.DataFrame, share: np.ndarray,
              sources: tuple[str, ...], chans: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Customer journeys for attribution.

    Every recorded new customer gets a path of 1 + Poisson(m) touches drawn from channels in
    proportion to that geo-week's clicks (organic/direct in proportion to organic sessions,
    down-weighted). If the causal source is a paid channel it is guaranteed to appear (before
    the last position where possible). Independently of the causal source, with probability
    `harvest_last_touch_prob` the final touch is a harvest channel (brand search or
    retargeting, by clicks): harvest channels collect last-click credit for demand they did
    not create. A weighted sample of non-converting journeys is added for Markov attribution.
    """
    touch = (*chans, *ORGANIC_TOUCHES)
    P = len(touch)
    clicks = media.pivot_table(index=["geo", "week_start"], columns="channel",
                               values="clicks", aggfunc="sum")[chans]
    idx = pd.MultiIndex.from_arrays([outcomes.geo, outcomes.week_start])
    cl = clicks.reindex(idx).to_numpy()
    org = (sessions.set_index(["geo", "week_start"]).organic_direct_sessions
           .reindex(idx).to_numpy())
    # Most organic sessions are browsing that never becomes a tracked marketing touch.
    weights = np.column_stack([cl, 0.25 * 0.55 * org, 0.25 * 0.45 * org])
    cum = np.cumsum(weights / weights.sum(axis=1, keepdims=True), axis=1)
    hv = [chans.index(h) for h in HARVEST if h in chans]
    hv_w = cl[:, hv] if hv else np.zeros((len(cl), 1))
    hv_p = hv_w / np.maximum(hv_w.sum(axis=1, keepdims=True), 1e-12)
    lmax = 12

    def _paths(cell: np.ndarray, extra_mean: float, p_h: float,
               src: np.ndarray | None) -> np.ndarray:
        m = cell.size
        L = 1 + np.minimum(rng.poisson(extra_mean, m), lmax - 3)
        u = rng.random((m, lmax))
        t = np.empty((m, lmax), dtype=np.int64)
        cc = cum[cell]
        for k in range(lmax):  # inverse-CDF draw, one column at a time (memory-light)
            t[:, k] = (u[:, k][:, None] > cc).sum(axis=1)
        t = t.clip(max=P - 1)
        pos = np.arange(lmax)[None, :]
        t[pos >= L[:, None]] = -1
        rows = np.arange(m)
        if src is not None:
            fix = (src >= 0) & ~(t == src[:, None]).any(axis=1)
            ins = np.floor(rng.random(m) * np.maximum(L - 1, 1)).astype(int)
            t[rows[fix], ins[fix]] = src[fix]
        if hv:
            flag = rng.random(m) < p_h
            hch = np.where(rng.random(m) < hv_p[cell, 0], hv[0], hv[-1])
            last = t[rows, L - 1]
            if src is not None:
                own = src >= 0
                before = np.where(pos < (L - 1)[:, None], t, -1)
                only_last = own & (last == src) & ~(before == src[:, None]).any(axis=1)
            else:
                only_last = np.zeros(m, dtype=bool)
            app = flag & only_last  # keep the causal touch, append the harvest touch
            rep = flag & ~app
            t[rows[rep], L[rep] - 1] = hch[rep]
            t[rows[app], L[app]] = hch[app]
        return t

    n_cell = outcomes.new_customers.to_numpy().astype(np.int64)
    sh = share.reshape(share.shape[0], -1).T  # [cells, S]; geo-major like outcomes
    rev_per = outcomes.first_order_revenue.to_numpy() / np.maximum(n_cell, 1)

    cell = np.repeat(np.arange(n_cell.size), n_cell)
    cdf_s = np.cumsum(sh, axis=1)[cell]
    s_idx = (rng.random(cell.size)[:, None] > cdf_s).sum(axis=1).clip(max=len(sources) - 1)
    src = s_idx - 1  # -1 = baseline (non-paid); otherwise an index into chans
    t_conv = _paths(cell, cfg.path_extra_touches_mean, cfg.harvest_last_touch_prob, src)
    n_nc = np.round(n_cell * cfg.nonconverting_paths_per_converter).astype(np.int64)
    cell_nc = np.repeat(np.arange(n_cell.size), n_nc)
    t_nc = _paths(cell_nc, 1.0, cfg.harvest_last_touch_prob * 0.4, None)

    labels = np.array(touch)

    def _strings(t: np.ndarray) -> list[str]:
        return [">".join(labels[row[row >= 0]]) for row in t]

    geo = outcomes.geo.to_numpy()
    wk = outcomes.week_start.to_numpy()
    conv = pd.DataFrame({"geo": geo[cell], "week_start": wk[cell], "converted": True,
                         "weight": 1.0, "path": _strings(t_conv),
                         "first_order_revenue": rev_per[cell]})
    nonconv = pd.DataFrame({"geo": geo[cell_nc], "week_start": wk[cell_nc], "converted": False,
                            "weight": cfg.nonconverting_weight, "path": _strings(t_nc),
                            "first_order_revenue": 0.0})
    jr = pd.concat([conv, nonconv], ignore_index=True)
    jr.insert(0, "journey_id", [f"J{k:07d}" for k in range(len(jr))])
    jr["n_touches"] = jr.path.str.count(">") + 1
    js = pd.DataFrame({"journey_id": jr.journey_id.to_numpy()[: len(conv)],
                       "causal_source": np.array(sources)[s_idx]})
    return jr, js
