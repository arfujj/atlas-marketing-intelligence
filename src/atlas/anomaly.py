"""Anomaly engine: seasonal baseline → robust z → decomposition → ranked hypotheses.

1. Baseline. For every evaluation period t a robust (Huber) regression on log(metric) is fit on
   the trailing history only (no look-ahead): intercept, linear trend, seasonal terms (yearly
   Fourier for weekly data, day-of-week for daily data) and holiday / promotion flags.
2. Score. The residual at t is standardised by the median and MAD (×1.4826) of the in-sample
   residuals of that same trailing fit: a robust z-score, insensitive to past anomalies.
3. Threshold. |z| thresholds are calibrated empirically: for Halden on simulated worlds with no
   incidents (the detector's false-alarm rate is a property of the method and the noise); for
   GA4, where no clean reference exists, the conventional robust cut-off |z| ≥ 3.5 is used.
4. Explain. Region shift-share and channel price/volume decomposition say *where* a change
   sits; related indicators (sessions, CTR, CPC, conversion rate) say *what kind* of change it
   is. Hypotheses carry an evidence status: Confirmed (the data itself proves the statement,
   e.g. an arithmetic decomposition), Supported hypothesis (pattern consistent, cause not
   independently verified) or Unverified. A decomposition never identifies a cause.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MAD_K = 1.4826
GA4_THRESHOLD = 3.5


# --------------------------------------------------------------------------- robust fit


def huber_fit(X: np.ndarray, y: np.ndarray, k: float = 1.345, iters: int = 30) -> np.ndarray:
    """Huber M-estimate by iteratively reweighted least squares."""
    w = np.ones_like(y)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    for _ in range(iters):
        r = y - X @ beta
        s = MAD_K * np.median(np.abs(r - np.median(r))) or 1e-9
        u = np.abs(r / s)
        w = np.where(u <= k, 1.0, k / np.maximum(u, 1e-12))
        sw = np.sqrt(w)
        new = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        if np.allclose(new, beta, atol=1e-8):
            beta = new
            break
        beta = new
    return beta


def weekly_features(weeks: pd.DatetimeIndex, flags: pd.DataFrame | None, k: int = 2):
    t = np.arange(len(weeks)) / 52.0
    doy = weeks.day_of_year.to_numpy()
    cols = [np.ones(len(weeks)), t]
    for i in range(1, k + 1):
        ang = 2 * np.pi * i * doy / 365.25
        cols += [np.sin(ang), np.cos(ang)]
    if flags is not None:
        cols += [flags[c].to_numpy(dtype=float) for c in flags.columns]
    return np.column_stack(cols)


def daily_features(days: pd.DatetimeIndex, flags: pd.DataFrame | None):
    t = np.arange(len(days)) / 30.0
    dow = days.dayofweek.to_numpy()
    cols = [np.ones(len(days)), t] + [(dow == d).astype(float) for d in range(1, 7)]
    if flags is not None:
        cols += [flags[c].to_numpy(dtype=float) for c in flags.columns]
    return np.column_stack(cols)


def robust_z(y: pd.Series, X: np.ndarray, start: int, min_train: int,
             window: int | None = None) -> pd.DataFrame:
    """Expanding (or trailing-`window`) one-step-ahead robust z-scores on log(y).

    Returns rows for t ≥ start with expected value, actual, z and the fit size.
    """
    v = np.log(np.maximum(y.to_numpy(dtype=float), 1e-9))
    rows = []
    for t in range(max(start, min_train), len(v)):
        lo = 0 if window is None else max(0, t - window)
        Xt, yt = X[lo:t], v[lo:t]
        keep = np.ptp(Xt, axis=0) > 0
        keep[0] = True  # intercept
        b = huber_fit(Xt[:, keep], yt)
        res = yt - Xt[:, keep] @ b
        med = np.median(res)
        mad = MAD_K * np.median(np.abs(res - med))
        pred = float(X[t, keep] @ b + med)
        z = (v[t] - pred) / mad if mad > 0 else 0.0
        rows.append({"period": y.index[t], "actual": float(y.iloc[t]),
                     "expected": float(np.exp(pred)), "z": float(z),
                     "pct_dev": float(np.exp(v[t] - pred) - 1), "n_train": t - lo})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Halden panel


HALDEN_NATIONAL = ("revenue", "new_customers", "orders", "sessions", "conversion_rate")
HALDEN_REGIONAL = ("revenue", "orders", "conversion_rate", "sessions")
HALDEN_CHANNEL = ("spend", "clicks", "cpc", "ctr")


def halden_panel(media: pd.DataFrame, outcomes: pd.DataFrame, sessions: pd.DataFrame
                 ) -> dict[str, pd.Series]:
    """All monitored series, keyed 'national:metric', 'region:R03:metric', 'channel:c:metric'."""
    o = outcomes.merge(sessions, on=["week_start", "geo"])
    o["week_start"] = pd.to_datetime(o.week_start)
    nat = o.groupby("week_start")[["revenue", "new_customers", "orders", "sessions"]].sum()
    nat["conversion_rate"] = nat.orders / nat.sessions
    out = {f"national:{m}": nat[m] for m in HALDEN_NATIONAL}
    reg = o.set_index(["geo", "week_start"])
    for g in sorted(o.geo.unique()):
        r = reg.loc[g]
        r = r.assign(conversion_rate=r.orders / r.sessions)
        for m in HALDEN_REGIONAL:
            out[f"region:{g}:{m}"] = r[m]
    m = media.assign(week_start=pd.to_datetime(media.week_start))
    ch = m.groupby(["channel", "week_start"])[["spend", "clicks", "impressions"]].sum()
    for c in sorted(m.channel.unique()):
        x = ch.loc[c]
        x = x.assign(cpc=x.spend / x.clicks, ctr=x.clicks / x.impressions)
        for k in HALDEN_CHANNEL:
            out[f"channel:{c}:{k}"] = x[k]
    return out


def score_halden(media, outcomes, sessions, calendar, eval_weeks: int = 52,
                 min_train: int = 78) -> pd.DataFrame:
    panel = halden_panel(media, outcomes, sessions)
    cal = calendar.assign(week_start=pd.to_datetime(calendar.week_start)).set_index(
        "week_start")
    rows = []
    for key, s in panel.items():
        s = s.sort_index()
        # Undefined ratios (e.g. CPC before a channel launches) are not monitored.
        s = s[np.isfinite(s) & (s > 0)]
        if len(s) < min_train + 1:
            continue
        flags = cal.reindex(s.index)[["promo_week", "bfcm_week", "gifting_week"]]
        X = weekly_features(pd.DatetimeIndex(s.index), flags)
        z = robust_z(s, X, start=len(s) - eval_weeks, min_train=min_train)
        z["series"] = key
        rows.append(z)
    df = pd.concat(rows, ignore_index=True)
    parts = df.series.str.split(":", expand=True)
    df["level"], df["entity"], df["metric"] = parts[0], parts[1], parts[2].fillna(parts[1])
    df.loc[df.level == "national", "entity"] = "ALL"
    return df


def family(series: pd.Series) -> pd.Series:
    return series.str.split(":").str[0]


def calibrate_thresholds(null_scores: list[pd.DataFrame], fpr: float = 0.005) -> dict:
    """|z| threshold per series family so that the per-series-week false-alarm rate on
    incident-free worlds is `fpr`."""
    z = pd.concat(null_scores, ignore_index=True)
    return {f: float(np.quantile(np.abs(g.z), 1 - fpr)) for f, g in z.groupby(family(z.series))}


def alerts(scores: pd.DataFrame, thresholds: dict | float) -> pd.DataFrame:
    thr = (scores.series.map(lambda s: thresholds[s.split(":")[0]])
           if isinstance(thresholds, dict) else thresholds)
    a = scores[np.abs(scores.z) >= thr].copy()
    a["threshold"] = thr[a.index] if not np.isscalar(thr) else thr
    return a


def match_incidents(al: pd.DataFrame, incidents: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Grade alerts against injected incidents (truth). An alert is a true positive when its
    week falls inside an incident and its entity matches the incident's scope: a regional
    outage → that region (or national); a checkout incident → national or any region; a CPC
    spike → that channel."""
    al = al.copy()
    al["incident_id"] = None
    inc = incidents.assign(start_week=pd.to_datetime(incidents.start_week),
                           end_week=pd.to_datetime(incidents.end_week))
    for i, a in al.iterrows():
        for _, r in inc.iterrows():
            if not (r.start_week <= pd.Timestamp(a.period) <= r.end_week):
                continue
            ok = ((r.kind == "cpc_spike" and a.level == "channel" and a.entity == r.channel)
                  or (r.kind == "tracking_outage" and (a.entity == r.geo
                                                        or a.level == "national"))
                  or (r.kind == "checkout_incident" and a.level in ("national", "region")))
            if ok:
                al.at[i, "incident_id"] = r.incident_id
                break
    events = al.groupby(["period", "level", "entity"]).incident_id.first().reset_index()
    tp = events.incident_id.notna().sum()
    detected = set(al.incident_id.dropna())
    stats = {"alert_events": int(len(events)), "true_positive_events": int(tp),
             "precision": float(tp / len(events)) if len(events) else None,
             "incidents": int(len(inc)), "detected": int(len(detected)),
             "recall": float(len(detected) / len(inc)) if len(inc) else None,
             "detected_ids": sorted(detected)}
    return al, stats


# --------------------------------------------------------------------------- explain


def region_shift_share(outcomes: pd.DataFrame, sessions: pd.DataFrame, week,
                       base_weeks: int = 8) -> pd.DataFrame:
    """Decompose the change in national revenue and conversion rate at `week` vs the mean of
    the previous `base_weeks` weeks into regional contributions.

    Conversion rate change = mix (traffic share shifts) + rate (regional CR changes):
        Δcr = Σ_g (s_g,t − s_g,0)·cr_g,0  +  Σ_g s_g,t·(cr_g,t − cr_g,0)
    """
    o = outcomes.merge(sessions, on=["week_start", "geo"])
    o["week_start"] = pd.to_datetime(o.week_start)
    week = pd.Timestamp(week)
    cur = o[o.week_start == week].set_index("geo")
    base = (o[(o.week_start < week) & (o.week_start >= week - pd.Timedelta(weeks=base_weeks))]
            .groupby("geo")[["revenue", "orders", "sessions"]].mean())
    s1, s0 = cur.sessions / cur.sessions.sum(), base.sessions / base.sessions.sum()
    cr1, cr0 = cur.orders / cur.sessions, base.orders / base.sessions
    d_rev = cur.revenue - base.revenue
    return pd.DataFrame({
        "revenue_change": d_rev, "revenue_change_share": d_rev / d_rev.sum(),
        "cr_mix_effect": (s1 - s0) * cr0, "cr_rate_effect": s1 * (cr1 - cr0),
        "sessions_change_pct": cur.sessions / base.sessions - 1,
        "cr_change_pct": cr1 / cr0 - 1,
    }).sort_values("revenue_change")


def channel_price_volume(media: pd.DataFrame, week, base_weeks: int = 8) -> pd.DataFrame:
    """Spend change by channel = volume (clicks) effect + price (CPC) effect (exact)."""
    m = media.assign(week_start=pd.to_datetime(media.week_start))
    week = pd.Timestamp(week)
    cur = m[m.week_start == week].groupby("channel")[["spend", "clicks", "impressions"]].sum()
    base = (m[(m.week_start < week) & (m.week_start >= week - pd.Timedelta(weeks=base_weeks))]
            .groupby(["channel", "week_start"])[["spend", "clicks", "impressions"]].sum()
            .groupby("channel").mean())
    cpc0, cpc1 = base.spend / base.clicks, cur.spend / cur.clicks
    return pd.DataFrame({
        "spend_change": cur.spend - base.spend,
        "volume_effect": (cur.clicks - base.clicks) * cpc0,
        "price_effect": cur.clicks * (cpc1 - cpc0),
        "cpc_change_pct": cpc1 / cpc0 - 1,
        "clicks_change_pct": cur.clicks / base.clicks - 1,
        "ctr_change_pct": (cur.clicks / cur.impressions) / (base.clicks / base.impressions) - 1,
    }).sort_values("spend_change", ascending=False)


@dataclass
class Hypothesis:
    title: str
    status: str  # Confirmed / Supported hypothesis / Unverified
    evidence: list[str]
    follow_ups: list[str]
    score: float


def explain_week(scores: pd.DataFrame, media, outcomes, sessions, week,
                 thresholds: dict) -> dict:
    """Ranked hypotheses for one week, from the scores of every monitored series."""
    wk = pd.Timestamp(week)
    s = scores[pd.to_datetime(scores.period) == wk].set_index("series")
    z = s.z.to_dict()
    thr = lambda key: thresholds[key.split(":")[0]]  # noqa: E731
    flagged = {k: v for k, v in z.items() if abs(v) >= thr(k)}
    hyps: list[Hypothesis] = []
    regions = sorted({k.split(":")[1] for k in z if k.startswith("region:")})

    # Regional conversion drop with normal sessions → tracking or regional site problem
    reg_cr = {g: z.get(f"region:{g}:conversion_rate", 0.0) for g in regions}
    low = [g for g, v in reg_cr.items() if v <= -thr(f"region:{g}:x")]
    nat_ses = z.get("national:sessions", 0.0)
    # Site-wide conversion drop with normal sessions → checkout / site-wide failure
    widespread = [g for g, v in reg_cr.items() if v <= -2.0]
    nat_cr = z.get("national:conversion_rate", 0.0)
    site_wide = (nat_cr <= -thr("national:x")
                 and len(widespread) >= max(3, len(regions) // 2))
    if site_wide:
        hyps.append(Hypothesis(
            "Site-wide conversion failure (checkout/payment) or site-wide tracking failure",
            "Supported hypothesis" if abs(nat_ses) < thr("national:x") else "Unverified",
            [f"National conversion rate z = {nat_cr:.1f}; sessions z = {nat_ses:.1f}",
             f"{len(widespread)} of {len(regions)} regions with conversion z ≤ −2"],
            ["Check checkout error rates and payment-provider status for the week",
             "Reconcile recorded orders with the order database to separate a real loss "
             "from a tracking gap", "Check whether new and repeat orders fell alike"],
            score=-nat_cr + 1))
    # A site-wide drop also pushes some regions past the threshold; that is not a regional
    # tracking problem, so the regional hypothesis is only offered when the drop is local.
    if low and len(low) <= 2 and not site_wide:
        ses_ok = all(abs(z.get(f"region:{g}:sessions", 0.0)) < thr("region:x") for g in low)
        ev = [f"{g}: conversion rate z = {reg_cr[g]:.1f}, sessions z = "
              f"{z.get(f'region:{g}:sessions', 0.0):.1f}" for g in low]
        others = [abs(v) for g, v in reg_cr.items() if g not in low]
        ev.append(f"Other regions: max |z| of conversion rate {max(others):.1f}")
        hyps.append(Hypothesis(
            f"Measurement failure in {', '.join(low)} (purchase tracking under-recording)",
            "Supported hypothesis" if ses_ok else "Unverified", ev,
            ["Compare recorded orders with the payment processor / order database for "
             f"{', '.join(low)}", "Check tag-manager deploys and consent-banner changes",
             "Do not change budgets for these regions until resolved"],
            score=-min(reg_cr[g] for g in low) + (2 if ses_ok else 0)))
    # Demand / traffic change
    if abs(nat_ses) >= thr("national:x"):
        hyps.append(Hypothesis(
            f"Traffic {'drop' if nat_ses < 0 else 'surge'} (demand or acquisition change)",
            "Supported hypothesis", [f"National sessions z = {nat_ses:.1f}"],
            ["Break sessions down by paid vs organic/direct", "Check media delivery"],
            score=abs(nat_ses)))
    # CPC spikes: decomposition makes the price effect a confirmed fact
    pv = channel_price_volume(media, wk)
    for c in pv.index:
        zc = z.get(f"channel:{c}:cpc", 0.0)
        if zc >= thr("channel:x"):
            row = pv.loc[c]
            hyps.append(Hypothesis(
                f"{c}: cost per click up {row.cpc_change_pct:+.0%} with clicks "
                f"{row.clicks_change_pct:+.0%}",
                "Confirmed",
                [f"Spend change ${row.spend_change:,.0f} = price effect "
                 f"${row.price_effect:,.0f} + volume effect ${row.volume_effect:,.0f}",
                 f"CPC z = {zc:.1f}; CTR change {row.ctr_change_pct:+.0%}"],
                ["Cause (auction competition, bid-strategy change, quality score) is "
                 "Unverified: check auction insights and bid-strategy change history",
                 "Extra spend bought no extra clicks; consider capping bids"],
                score=zc))
    hyps.sort(key=lambda h: -h.score)
    shift = region_shift_share(outcomes, sessions, wk)
    return {"week": str(wk.date()), "flagged_series": flagged,
            "hypotheses": [h.__dict__ for h in hyps],
            "region_shift_share": shift.reset_index().to_dict("records"),
            "channel_price_volume": pv.reset_index().to_dict("records")}


# --------------------------------------------------------------------------- GA4


def ga4_holiday_flags(days: pd.DatetimeIndex) -> pd.DataFrame:
    d = days.normalize()
    bfcm = (d >= "2020-11-27") & (d <= "2020-11-30")
    holiday = (d >= "2020-12-21") & (d <= "2021-01-01")
    return pd.DataFrame({"bfcm": bfcm.astype(float), "holiday": holiday.astype(float)},
                        index=days)


GA4_METRICS = ("sessions", "purchase_events", "purchase_sessions", "transactions", "revenue",
               "session_conversion_rate", "ev_add_to_cart", "ev_begin_checkout",
               "revenue_per_purchase_event", "identified_share")


def ga4_series(daily: pd.DataFrame) -> dict[str, pd.Series]:
    d = daily.assign(date=pd.to_datetime(daily.date)).set_index("date").sort_index()
    d["revenue_per_purchase_event"] = d.revenue_naive / d.purchase_events
    d["identified_share"] = 1 - d.unidentified_purchase_events / d.purchase_events
    return {m: d[m] for m in GA4_METRICS}


def score_ga4(daily: pd.DataFrame, window: int = 35, min_train: int = 28) -> pd.DataFrame:
    rows = []
    for m, s in ga4_series(daily).items():
        days = pd.DatetimeIndex(s.index)
        X = daily_features(days, ga4_holiday_flags(days))
        z = robust_z(s.clip(lower=1e-6), X, start=min_train, min_train=min_train,
                     window=window)
        z["series"] = m
        rows.append(z)
    return pd.concat(rows, ignore_index=True)


def ga4_late_january(daily: pd.DataFrame, scores: pd.DataFrame,
                     start: str = "2021-01-26") -> dict:
    """Demand change or instrumentation? Compare purchase events and upstream funnel steps
    with the fields that carry revenue and transaction ids, before vs after `start`."""
    d = daily.assign(date=pd.to_datetime(daily.date)).set_index("date").sort_index()
    after = d[d.index >= start]
    before = d[(d.index < start) & (d.index >= pd.Timestamp(start) - pd.Timedelta(days=14))]

    def per_day(df, c):
        return float(df[c].sum() / len(df))

    cols = ["sessions", "ev_add_to_cart", "ev_begin_checkout", "purchase_events",
            "purchase_sessions", "transactions", "revenue", "unidentified_purchase_events"]
    comp = {c: {"before_per_day": per_day(before, c), "after_per_day": per_day(after, c),
                "change_pct": per_day(after, c) / per_day(before, c) - 1} for c in cols}
    ratios = {
        "purchase_events_per_1k_sessions": (1000 * before.purchase_events.sum()
                                            / before.sessions.sum(),
                                            1000 * after.purchase_events.sum()
                                            / after.sessions.sum()),
        "purchase_events_per_begin_checkout": (
            before.purchase_events.sum() / before.ev_begin_checkout.sum(),
            after.purchase_events.sum() / after.ev_begin_checkout.sum()),
        "revenue_per_purchase_event": (before.revenue_naive.sum() / before.purchase_events.sum(),
                                       after.revenue_naive.sum() / after.purchase_events.sum()),
        "identified_transaction_share": (
            1 - before.unidentified_purchase_events.sum() / before.purchase_events.sum(),
            1 - after.unidentified_purchase_events.sum() / after.purchase_events.sum()),
    }
    sc = scores[pd.to_datetime(scores.period) >= start]
    zmin = sc.groupby("series").z.min().to_dict()
    zmax = sc.groupby("series").z.max().to_dict()
    demand_stable = (abs(comp["purchase_events"]["change_pct"]) < 0.25
                     and abs(comp["ev_begin_checkout"]["change_pct"]) < 0.25)
    payload_broken = (ratios["identified_transaction_share"][1] < 0.5
                      and ratios["revenue_per_purchase_event"][1]
                      < 0.5 * ratios["revenue_per_purchase_event"][0])
    if demand_stable and payload_broken:
        conclusion = ("Instrumentation, not demand. From 2021-01-26 purchase events, purchasing "
                      "sessions and upstream funnel steps continue at their usual rates, but the "
                      "transaction_id and revenue fields of the purchase event go missing "
                      "('(not set)' ids, near-zero revenue). Deduplicated transactions and "
                      "revenue therefore fall although purchasing behaviour did not.")
        status = "Supported hypothesis"
        note = ("Not 'Confirmed': confirmation needs an independent source (order database or "
                "tag-deployment log), which the public sample does not include.")
    else:
        conclusion = "Pattern inconclusive; see the comparison table."
        status = "Unverified"
        note = ""
    return {"start": start, "comparison": comp,
            "ratios": {k: {"before": v[0], "after": v[1]} for k, v in ratios.items()},
            "z_min_after": zmin, "z_max_after": zmax, "conclusion": conclusion,
            "evidence_status": status, "status_note": note,
            "follow_ups": ["Reconcile purchase events with the order system for 26–31 Jan",
                           "Check the purchase tag's ecommerce payload (transaction_id, value) "
                           "in the tag-manager version history",
                           "Exclude 26–31 Jan revenue from trend reporting until resolved"]}
