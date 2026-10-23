"""Flagship Halden run: `python -m atlas.pipeline.halden` (part of `make models`).

Writes, under model_runs/:
  mmm-halden-*/        posterior draws (1000), diagnostics, ROI summary per MMM variant
  halden-*/summary.json  measurement scorecard vs truth, holdout validation, VOI ranking and
                         design/power table, geo-lift readout, optimizer recommendation for the
                         $500K question, sensitivity tornado and true regret
All numbers quoted in the docs come from these files (run ids in the manifests).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from atlas.attribution import attribution_table
from atlas.geolift import design_sigma, power, stratified_holdout
from atlas.mmm.fit import ols_naive, save_fit
from atlas.optimizer import OBJECTIVES, optimize, tornado, true_evaluation
from atlas.pipeline.measure import (
    OBJECTIVE,
    current_plan,
    default_constraints,
    economics_from_observed,
    measure_world,
    observed_ranges,
)
from atlas.runs import dump_json, make_run_id, run_dir, write_manifest
from atlas.sim import default_world, simulate
from atlas.voi import evpi, predicted_test_effect, rank_experiments

SEED = 20261023
BUDGET = 500_000.0


def _ols_holdout(d) -> dict:
    n = len(d.weeks) - 13
    o = ols_naive(d, n_train=n)
    X = np.column_stack([np.ones(len(d.weeks)), d.spend])
    y_tr = d.y[:n]
    coef, *_ = np.linalg.lstsq(X[:n], y_tr, rcond=None)
    pred = X[n:] @ coef
    return {"mape": float(np.mean(np.abs(pred - d.y[n:]) / d.y[n:])),
            "roi": o.set_index("channel").roi_mean.to_dict()}


def main(argv: list[str] | None = None) -> str:
    p = argparse.ArgumentParser(prog="atlas.pipeline.halden")
    p.add_argument("--draws", type=int, default=2000)
    p.add_argument("--tune", type=int, default=2000)
    p.add_argument("--chains", type=int, default=4)
    p.add_argument("--n-sim-voi", type=int, default=300)
    a = p.parse_args(argv)
    started = datetime.now(UTC)
    world = simulate(default_world(), seed=SEED)
    res = measure_world(world, SEED, draws=a.draws, tune=a.tune, chains=a.chains, keep=1000,
                        holdout=True, n_sim_voi=a.n_sim_voi, budget=BUDGET)
    d = res["design"]
    fits = res["fits"]
    meta = {"seed": SEED, "company": world.config.company,
            "config_fingerprint": world.config.fingerprint()}
    run_ids = {name: save_fit(fr, d, meta, SEED, tag="halden") for name, fr in fits.items()}

    econ = economics_from_observed(world.outcomes)
    current, budget = current_plan(world.media, BUDGET)
    cons = default_constraints(current, budget)
    obs = observed_ranges(d)
    recommended = "bayes_dag_calibrated"
    post = fits[recommended].posterior

    # Optimizer results for every objective on the recommended model, plus true grading.
    opt = {}
    for o in OBJECTIVES:
        r = optimize(post, cons, o, econ, current, obs, run_id=run_ids[recommended])
        plan = {c.channel: c.proposed for c in r.channels}
        truth = true_evaluation(world, {"proposed": plan, "current": current}, cons, o)
        opt[o] = r.to_dict() | {"true": truth}
    alts = {f"Model: {fits[k].variant.label}": fits[k].posterior
            for k in ("bayes_dag", "bayes_default")}
    torn = tornado(post, cons, OBJECTIVE, econ, current, obs, alt_posteriors=alts)

    # Design / power table: duration × holdout size for every channel (pre-test, observed only)
    ho1 = stratified_holdout(list(world.geos), list(world.config.geo_weights), SEED)
    ho2 = stratified_holdout(list(world.geos), list(world.config.geo_weights), SEED,
                             per_stratum=2)
    design_rows, designs_all = [], {}
    for label, ho in (("1 region per stratum", ho1), ("2 regions per stratum", ho2)):
        for weeks in (6, 8):
            for c in d.channels:
                ds = design_sigma(world.outcomes, world.media, c, ho, test_weeks=weeks)
                eff = predicted_test_effect(post, c, ds["x_national_weekly"], weeks)
                design_rows.append({
                    "channel": c, "holdout": list(ho), "holdout_label": label,
                    "test_weeks": weeks, "sigma_national": ds["sigma_national"],
                    "predicted_effect_mean": float(eff.mean()),
                    "power": float(np.mean(power(eff, ds["sigma_national"]))),
                    "mde90": float(ds["sigma_national"] * 2.49)})  # 80% power, α=0.10
                designs_all[(label, weeks, c)] = ds
    # EVSI for every design on the calibrated (post-test) posterior: the NEXT experiment.
    next_rows = []
    for (label, weeks) in {(k[0], k[1]) for k in designs_all}:
        ds = {c: designs_all[(label, weeks, c)] for c in d.channels}
        for r in rank_experiments(post, cons, OBJECTIVE, econ, ds, n_sim=a.n_sim_voi,
                                  seed=SEED):
            r["holdout_label"] = label
            next_rows.append(r)
    next_rows.sort(key=lambda r: -r["evsi"])
    value_pi = evpi(post, cons, OBJECTIVE, econ)

    att = attribution_table(world.journeys, world.media)
    summary = {
        "label": "SIMULATED — Halden Coffee Works is fictional; truth is used only to grade.",
        "seed": SEED, "config_fingerprint": world.config.fingerprint(),
        "budget": budget, "objective": OBJECTIVE, "economics": asdict(econ),
        "current": current, "constraints": asdict(cons), "observed_ranges": obs,
        "mmm_runs": run_ids, "recommended_variant": recommended,
        "estimates": res["estimates"], "truth": world.truth_channels.to_dict("records"),
        "diagnostics": res["diagnostics"], "holdout": res["holdout"] | {
            "ols_naive": _ols_holdout(d)},
        "voi_first": res["voi"], "geolift": res["geolift"],
        "plans": res["plans"], "graded": res["graded"], "optimizer": opt,
        "tornado": torn, "design_power": design_rows, "next_experiments": next_rows,
        "evpi": value_pi,
        "attribution": att.replace({np.nan: None}).to_dict("records"),
    }
    cfg = {"seed": SEED, "draws": a.draws, "tune": a.tune, "chains": a.chains,
           "budget": budget, "objective": OBJECTIVE, "mmm_runs": run_ids}
    run_id = make_run_id("halden", SEED, cfg)
    out = run_dir(run_id)
    dump_json(out / "summary.json", summary)
    pd.DataFrame(res["estimates"]).to_parquet(out / "estimates.parquet", index=False)
    write_manifest(run_id, "halden", "Simulated", cfg, {"summary": "summary.json"},
                   started_at=started)
    print(run_id)
    return run_id


if __name__ == "__main__":
    main()
