"""Multi-world scorecard: `python -m atlas.pipeline.scorecard --worlds 24 --jobs 3`.

Each world is drawn by `sample_world(seed)` (randomised parameters and regime, see
docs/data-generating-process.md §7) and measured end to end by `measure_world` with fewer
posterior draws than the flagship. Every method is graded against that world's truth:
per-channel ROI error, 90% interval coverage, and true regret of the plan it recommends.
Failures are kept and reported, not filtered.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.runs import dump_json, make_run_id, run_dir, write_manifest

PLAN_ORDER = ("current", "last_click", "bayes_default", "bayes_dag", "bayes_dag_calibrated")


def _one(seed: int, draws: int, tune: int, chains: int, keep: int, n_sim: int,
         out: str) -> dict:
    os.environ.setdefault("PYTENSOR_FLAGS", f"compiledir={Path(out).parent}/.pytensor-{seed}")
    from atlas.pipeline.measure import measure_world
    from atlas.sim import simulate
    from atlas.sim.config import sample_world

    cfg, meta = sample_world(seed)
    world = simulate(cfg, seed=seed)
    logs = []
    r = measure_world(world, seed, draws=draws, tune=tune, chains=chains, keep=keep,
                      n_sim_voi=n_sim, log=logs.append)
    r.pop("fits")
    r.pop("design")
    r["regime"] = meta["regime"]
    r["world"] = meta
    r["log"] = logs
    dump_json(Path(out) / f"world_{seed:04d}.json", r)
    return r


def aggregate(worlds: list[dict]) -> dict:
    est = pd.DataFrame([e | {"seed": w["seed"], "regime": w["regime"]}
                        for w in worlds for e in w["estimates"]])
    est["rel_error"] = est.abs_error / est.true_roi
    by_method = est.groupby("method").agg(
        mean_abs_error=("abs_error", "mean"), median_abs_error=("abs_error", "median"),
        mean_rel_error=("rel_error", "mean"),
        coverage90=("covered90", lambda s: float(s.dropna().astype(float).mean())
                    if s.notna().any() else None))
    by_regime = (est.groupby(["regime", "method"]).abs_error.mean().unstack("method")
                 .round(4))
    by_channel = (est.groupby(["channel", "method"]).abs_error.mean().unstack("method")
                  .round(4))
    cov_regime = (est[est.covered90.notna()].assign(c=lambda x: x.covered90.astype(float))
                  .groupby(["regime", "method"]).c.mean().unstack("method").round(3))
    reg = []
    for w in worlds:
        g = w["graded"]
        best, cur = g["true_value_optimum"], g["plans"]["current"]["true_value"]
        gain = best - cur
        for name, v in g["plans"].items():
            reg.append({"seed": w["seed"], "regime": w["regime"], "plan": name,
                        "regret": v["regret"], "true_value": v["true_value"],
                        "achievable_gain": gain,
                        "regret_share": v["regret"] / gain if gain > 0 else None})
    reg = pd.DataFrame(reg)
    regret = reg.groupby("plan").agg(
        mean_regret=("regret", "mean"), median_regret=("regret", "median"),
        p90_regret=("regret", lambda s: float(np.percentile(s, 90))),
        median_regret_share=("regret_share", "median"),
        worse_than_current=("regret_share", lambda s: float((s > 1).mean())))
    diag = pd.DataFrame([{"seed": w["seed"], "variant": k, **{kk: v[kk] for kk in (
        "rhat_max", "ess_bulk_min", "divergences", "converged")}}
        for w in worlds for k, v in w["diagnostics"].items()])
    conv = diag.groupby("variant").agg(converged=("converged", "mean"),
                                       rhat_max_median=("rhat_max", "median"),
                                       divergent_fits=("divergences",
                                                       lambda s: int((s > 0).sum())))
    geo = pd.DataFrame([{"seed": w["seed"], "channel": w["geolift"]["channel"],
                         "delta_y": w["geolift"]["delta_y"],
                         "true": w["geolift"]["true_delta_y"], "se": w["geolift"]["se"],
                         "covered90": w["geolift"]["ci90"][0] <= w["geolift"]["true_delta_y"]
                         <= w["geolift"]["ci90"][1]} for w in worlds])
    cal = []
    for w in worlds:
        e = pd.DataFrame(w["estimates"])
        tested = w["geolift"]["channel"]
        sub = e[e.channel == tested].set_index("method")
        cal.append({"seed": w["seed"], "channel": tested,
                    "error_before": sub.loc["bayes_dag", "abs_error"],
                    "error_after": sub.loc["bayes_dag_calibrated", "abs_error"]})
    cal = pd.DataFrame(cal)
    failures = []
    for w in worlds:
        g = w["graded"]["plans"]
        if g["bayes_dag_calibrated"]["regret"] > g["current"]["regret"]:
            failures.append({"seed": w["seed"], "regime": w["regime"],
                             "what": "calibrated-MMM plan worse than current plan (true)",
                             "regret": g["bayes_dag_calibrated"]["regret"],
                             "regret_current": g["current"]["regret"]})
    return {
        "n_worlds": len(worlds),
        "regimes": pd.Series([w["regime"] for w in worlds]).value_counts().to_dict(),
        "roi_by_method": by_method.reset_index().to_dict("records"),
        "roi_error_by_regime": by_regime.reset_index().to_dict("records"),
        "roi_error_by_channel": by_channel.reset_index().to_dict("records"),
        "coverage_by_regime": cov_regime.reset_index().to_dict("records"),
        "regret_by_plan": regret.reset_index().to_dict("records"),
        "regret_rows": reg.to_dict("records"),
        "convergence": conv.reset_index().to_dict("records"),
        "geolift": {"coverage90": float(geo.covered90.mean()),
                    "mean_abs_error": float((geo.delta_y - geo.true).abs().mean()),
                    "mean_se": float(geo.se.mean()),
                    "tested_channels": geo.channel.value_counts().to_dict()},
        "calibration_effect_on_tested_channel": {
            "mean_error_before": float(cal.error_before.mean()),
            "mean_error_after": float(cal.error_after.mean()),
            "share_improved": float((cal.error_after < cal.error_before).mean())},
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> str:
    p = argparse.ArgumentParser(prog="atlas.pipeline.scorecard")
    p.add_argument("--worlds", type=int, default=24)
    p.add_argument("--first-seed", type=int, default=1)
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--draws", type=int, default=1000)
    p.add_argument("--tune", type=int, default=1000)
    p.add_argument("--chains", type=int, default=3)
    p.add_argument("--keep", type=int, default=500)
    p.add_argument("--n-sim-voi", type=int, default=150)
    a = p.parse_args(argv)
    started = datetime.now(UTC)
    seeds = list(range(a.first_seed, a.first_seed + a.worlds))
    cfg = {"seeds": seeds, "draws": a.draws, "tune": a.tune, "chains": a.chains,
           "keep": a.keep, "n_sim_voi": a.n_sim_voi}
    run_id = make_run_id("scorecard", f"{a.worlds}w", cfg)
    out = run_dir(run_id) / "worlds"
    out.mkdir(exist_ok=True)
    worlds = []
    done = {int(f.stem.split("_")[1]) for f in out.glob("world_*.json")}
    for s in sorted(done):
        worlds.append(json.loads((out / f"world_{s:04d}.json").read_text()))
    todo = [s for s in seeds if s not in done]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(_one, s, a.draws, a.tune, a.chains, a.keep, a.n_sim_voi,
                          str(out)): s for s in todo}
        for f in as_completed(futs):
            s = futs[f]
            try:
                worlds.append(f.result())
                print(f"world {s} done ({len(worlds)}/{len(seeds)})", flush=True)
            except Exception as e:  # noqa: BLE001 - a failed world is reported, not hidden
                print(f"world {s} FAILED: {e!r}", flush=True)
                (out / f"failed_{s:04d}.txt").write_text(repr(e))
    worlds.sort(key=lambda w: w["seed"])
    agg = aggregate(worlds)
    agg["failed_worlds"] = sorted(int(f.stem.split("_")[1]) for f in out.glob("failed_*.txt"))
    dump_json(out.parent / "scorecard.json", agg)
    write_manifest(run_id, "scorecard", "Simulated", cfg, {"scorecard": "scorecard.json",
                                                         "worlds": "worlds/"},
                   started_at=started)
    print(run_id)
    return run_id


if __name__ == "__main__":
    main()
