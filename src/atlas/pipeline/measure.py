"""Measure one simulated world end to end and grade every method against its truth.

Steps (the analyst side only ever sees observed tables; truth is used in `grade_*` only):
 1. national weekly design from observed media / outcomes / calendar
 2. naive OLS, Bayesian MMM (default priors), DAG-informed MMM
 3. optimizer on the DAG-informed posterior, value-of-information ranking of geo tests
 4. run the top-ranked geo-lift test in the simulated future (true DGP + noise), read it out
 5. calibrated MMM = DAG-informed + the lift-test likelihood term
 6. grade: per-channel ROI error and 90% coverage vs truth; true regret of each plan
"""

from __future__ import annotations

import time
from dataclasses import asdict

import numpy as np
import pandas as pd

from atlas.attribution import attribution_table
from atlas.geolift import GeoDesign, design_sigma, run_geolift, stratified_holdout
from atlas.mmm import calibrated_variant, dag_variant, default_variant, national_weekly
from atlas.mmm.fit import FitResult, fit, ols_naive, roi_summary
from atlas.optimizer import Constraints, Economics, optimize, true_evaluation
from atlas.voi import rank_experiments

OBJECTIVE = "profit_52w"
METHOD_LABELS = {
    "last_click": "Last-click attribution",
    "markov": "Markov attribution",
    "ols_naive": "Naive OLS (no controls)",
    "bayes_default": "Bayesian MMM, default priors",
    "bayes_dag": "MMM, DAG-informed priors",
    "bayes_dag_calibrated": "MMM + geo-lift calibration",
}


def economics_from_observed(outcomes: pd.DataFrame) -> Economics:
    """Default economics ASSUMPTIONS estimated from observed outcomes (blended)."""
    o = outcomes.assign(week_start=pd.to_datetime(outcomes.week_start))
    cm = o.first_order_contribution.sum() / o.first_order_revenue.sum()
    last = o[o.week_start > o.week_start.max() - pd.Timedelta(weeks=52)]
    k = last.repeat_contribution.sum() / last.first_order_contribution.sum()
    return Economics(cm_rate=float(cm), repeat_multiplier=float(k))


def current_plan(media: pd.DataFrame, budget: float | None = None,
                 step: float = 1_000.0) -> tuple[dict[str, float], float]:
    """Trailing-13-week billed spend by channel, scaled to the budget (default +5%)."""
    m = media.assign(week_start=pd.to_datetime(media.week_start))
    last = m[m.week_start > m.week_start.max() - pd.Timedelta(weeks=13)]
    q = last.groupby("channel").spend.sum()
    if budget is None:
        budget = float(np.round(q.sum() * 1.05 / step) * step)
    plan = (q / q.sum() * budget).to_dict()
    return {k: float(v) for k, v in plan.items()}, budget


def default_constraints(current: dict[str, float], budget: float, step: float = 1_000.0,
                        lo: float = 0.5, hi: float = 1.5) -> Constraints:
    """Guardrails: each channel between 50% and 150% of its current quarterly spend."""
    return Constraints(
        budget=budget,
        mins={c: float(np.floor(v * lo / step) * step) for c, v in current.items()},
        maxs={c: float(np.ceil(v * hi / step) * step) for c, v in current.items()},
        spend_all=True, step=step)


def observed_ranges(d) -> dict[str, dict]:
    s = d.spend
    return {c: {"min": float(s[s[:, j] > 0, j].min()), "max": float(s[:, j].max()),
                "last13_mean": float(s[-13:, j].mean())} for j, c in enumerate(d.channels)}


def lastclick_heuristic(roas: dict[str, float], cons: Constraints) -> dict[str, float]:
    """What a ROAS-driven team does: every channel at its minimum, then the remaining budget
    goes to channels in descending last-click ROAS, each up to its maximum."""
    plan = {c: cons.mins.get(c, 0.0) for c in roas}
    left = cons.budget - sum(plan.values())
    for c in sorted(roas, key=lambda k: -roas[k]):
        add = min(cons.maxs.get(c, cons.budget) - plan[c], left)
        plan[c] += add
        left -= add
    return plan


def measure_world(world, seed: int, *, draws: int = 1000, tune: int = 1000, chains: int = 4,
                  keep: int = 1000, holdout: bool = False, n_sim_voi: int = 200,
                  budget: float | None = None, log=print) -> dict:
    t0 = time.time()
    d = national_weekly(world.media, world.outcomes, world.calendar)
    T = len(d.weeks)
    fits: dict[str, FitResult] = {}
    holds: dict[str, dict] = {}
    kw = dict(draws=draws, tune=tune, chains=chains, keep=keep, seed=seed)
    for v in (default_variant(), dag_variant()):
        fits[v.name] = fit(d, v, **kw)
        dg = fits[v.name].diagnostics
        log(f"  fit {v.name}: {fits[v.name].seconds:.0f}s rhat {dg['rhat_max']:.3f}"
            f" div {dg['divergences']}")
        if holdout:
            holds[v.name] = fit(d, v, n_train=T - 13, **kw).diagnostics

    econ = economics_from_observed(world.outcomes)
    current, budget = current_plan(world.media, budget)
    cons = default_constraints(current, budget)
    obs = observed_ranges(d)

    # Value of information on the DAG-informed posterior → which channel to test.
    ho = stratified_holdout(list(world.geos), list(world.config.geo_weights), seed)
    designs = {c: design_sigma(world.outcomes, world.media, c, ho) for c in d.channels}
    voi = rank_experiments(fits["bayes_dag"].posterior, cons, OBJECTIVE, econ, designs,
                           n_sim=n_sim_voi, seed=seed)
    top = voi[0]["channel"]
    readout = run_geolift(world, GeoDesign(top, ho, tuple(g for g in world.geos
                                                         if g not in ho)), seed)
    log(f"  VOI top: {top}; geo-lift Δy {readout.delta_y:,.0f} (true "
        f"{readout.true_delta_y:,.0f}) se {readout.se:,.0f}")
    cal = calibrated_variant((readout.lift_test,))
    fits[cal.name] = fit(d, cal, **kw)
    if holdout:
        holds[cal.name] = fit(d, cal, n_train=T - 13, **kw).diagnostics

    # ---------------------------------------------------------------- estimates per method
    truth = world.truth_channels.set_index("channel")
    est = []
    ols = ols_naive(d).set_index("channel")
    att = attribution_table(world.journeys, world.media)
    for c in d.channels:
        t_roi = float(truth.loc[c, "true_roi_first_order_billed"])
        rows = [("ols_naive", ols.loc[c, "roi_mean"], ols.loc[c, "roi_p05"],
                 ols.loc[c, "roi_p95"])]
        for m in ("last_click", "markov"):
            r = att[(att.method == m) & (att.channel == c)].roas
            rows.append((m, float(r.iloc[0]) if len(r) else 0.0, np.nan, np.nan))
        for name, fr in fits.items():
            s = roi_summary(fr.posterior).set_index("channel").loc[c]
            rows.append((name, s.roi_mean, s.roi_p05, s.roi_p95))
        for m, mean, lo, hi in rows:
            est.append({"channel": c, "method": m, "roi_mean": float(mean),
                        "roi_p05": float(lo), "roi_p95": float(hi), "true_roi": t_roi,
                        "abs_error": abs(float(mean) - t_roi),
                        "covered90": (bool(lo <= t_roi <= hi) if np.isfinite(lo) else None)})

    # ---------------------------------------------------------------- plans and regret
    plans = {"current": current}
    opt = {}
    for name, fr in fits.items():
        r = optimize(fr.posterior, cons, OBJECTIVE, econ, current, obs, run_id=name)
        opt[name] = r
        plans[name] = {p.channel: p.proposed for p in r.channels}
    lc = att[att.method == "last_click"].set_index("channel").roas.reindex(d.channels)
    plans["last_click"] = lastclick_heuristic(lc.fillna(0).to_dict(), cons)
    graded = true_evaluation(world, plans, cons, OBJECTIVE)
    log(f"  done in {time.time() - t0:.0f}s")
    return {
        "seed": seed, "budget": budget, "objective": OBJECTIVE,
        "economics": asdict(econ), "current": current, "constraints": asdict(cons),
        "estimates": est, "voi": voi, "geolift": readout.to_dict(),
        "diagnostics": {k: {kk: vv for kk, vv in f.diagnostics.items() if kk != "ppc_band"}
                        for k, f in fits.items()},
        "holdout": {k: {kk: vv for kk, vv in v.items() if kk != "ppc_band"}
                    for k, v in holds.items()},
        "plans": plans, "graded": graded,
        "optimizer": {k: {"prob_beats_current": v.prob_proposed_beats_current,
                          "expected_uplift": v.uplift[OBJECTIVE]} for k, v in opt.items()},
        "fits": fits, "design": d, "seconds": time.time() - t0,
    }
