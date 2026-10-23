"""Anomaly run: `python -m atlas.pipeline.anomaly` (part of `make models`).

1. Calibrate |z| thresholds per series family on incident-free simulated worlds
   (target false-alarm rate per series-week, see `atlas.anomaly.calibrate_thresholds`).
2. Evaluate precision and recall on held-out worlds with random injected incidents (truth).
3. Flagship Halden world (scheduled incidents): alerts, grading and ranked hypotheses for
   every flagged week, including the final history week ("why did revenue fall?").
4. GA4 (observed): daily robust z-scores at |z| ≥ 3.5 and the late-January investigation.

Calibration and evaluation worlds use disjoint seeds, so the reported precision/recall is
out of sample. Halden numbers are Simulated; GA4 numbers are Observed.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from atlas.anomaly import (
    GA4_THRESHOLD,
    alerts,
    calibrate_thresholds,
    explain_week,
    ga4_late_january,
    match_incidents,
    score_ga4,
    score_halden,
)
from atlas.runs import dump_json, make_run_id, run_dir, write_manifest
from atlas.sim import default_world, simulate
from atlas.sim.config import sample_world

SEED = 20261023
FPR = 0.005
DUCKDB = Path(os.environ.get("ATLAS_DUCKDB", Path(__file__).resolve().parents[3]
                             / "data/serving/atlas.duckdb"))


def _scores(world) -> pd.DataFrame:
    return score_halden(world.media, world.outcomes, world.sessions, world.calendar)


def _world(seed: int, incidents: bool):
    cfg, meta = sample_world(seed)
    if not incidents:
        cfg = cfg.model_copy(update={"incident_mode": "none"})
    return simulate(cfg, seed=seed, journeys=False), meta


def evaluate(seeds: list[int], thresholds: dict) -> dict:
    rows, per_kind = [], []
    for s in seeds:
        w, meta = _world(s, incidents=True)
        al, st = match_incidents(alerts(_scores(w), thresholds), w.incidents)
        rows.append({"seed": s, "regime": meta["regime"]} | st)
        hit = set(st["detected_ids"])
        per_kind += [{"kind": r.kind, "magnitude": r.magnitude,
                      "detected": r.incident_id in hit} for r in w.incidents.itertuples()]
    df, pk = pd.DataFrame(rows), pd.DataFrame(per_kind)
    tp, ev = df.true_positive_events.sum(), df.alert_events.sum()
    return {
        "worlds": rows,
        "precision": float(tp / ev) if ev else None,
        "recall": float(df.detected.sum() / df.incidents.sum()),
        "alert_events": int(ev), "incidents": int(df.incidents.sum()),
        "recall_by_kind": pk.groupby("kind").detected.agg(["mean", "size"])
                            .rename(columns={"mean": "recall", "size": "n"})
                            .reset_index().to_dict("records"),
        "missed": pk[~pk.detected].to_dict("records"),
    }


def flagship(thresholds: dict) -> dict:
    w = simulate(default_world(), seed=SEED, journeys=False)
    sc = _scores(w)
    al, st = match_incidents(alerts(sc, thresholds), w.incidents)
    weeks = sorted(pd.to_datetime(al.period).unique())
    last = pd.Timestamp(w.outcomes.week_start.max())
    if last not in weeks:
        weeks.append(last)
    explained = [explain_week(sc, w.media, w.outcomes, w.sessions, wk, thresholds)
                 for wk in weeks]
    nat = sc[sc.level == "national"]
    return {"stats": st, "incidents": w.incidents.to_dict("records"),
            "alerts": al.to_dict("records"), "weeks": explained,
            "national_series": nat[["period", "metric", "actual", "expected", "z",
                                    "pct_dev"]].to_dict("records")}


def ga4() -> dict | None:
    if not DUCKDB.exists():
        return None
    import duckdb

    with duckdb.connect(str(DUCKDB), read_only=True) as c:
        tables = {r[0] for r in c.sql("select table_name from information_schema.tables "
                                      "where table_schema = 'ga4'").fetchall()}
        if "mart_ga4_daily" not in tables:
            return None
        daily = c.sql("select * from ga4.mart_ga4_daily order by date").df()
    sc = score_ga4(daily)
    al = alerts(sc, GA4_THRESHOLD)
    return {"threshold": GA4_THRESHOLD, "alerts": al.to_dict("records"),
            "scores": sc.to_dict("records"), "late_january": ga4_late_january(daily, sc)}


def main(argv: list[str] | None = None) -> str:
    p = argparse.ArgumentParser(prog="atlas.pipeline.anomaly")
    p.add_argument("--null-worlds", type=int, default=12)
    p.add_argument("--eval-worlds", type=int, default=12)
    a = p.parse_args(argv)
    started = datetime.now(UTC)
    null_seeds = list(range(1001, 1001 + a.null_worlds))
    eval_seeds = list(range(2001, 2001 + a.eval_worlds))
    thresholds = calibrate_thresholds([_scores(_world(s, incidents=False)[0])
                                       for s in null_seeds], fpr=FPR)
    out = {
        "label": "Halden sections are SIMULATED (truth used only to grade); GA4 is OBSERVED.",
        "fpr_target": FPR, "thresholds": thresholds,
        "calibration_seeds": null_seeds, "evaluation_seeds": eval_seeds,
        "evaluation": evaluate(eval_seeds, thresholds),
        "halden": flagship(thresholds),
        "ga4": ga4(),
    }
    cfg = {"seed": SEED, "fpr": FPR, "null_seeds": null_seeds, "eval_seeds": eval_seeds}
    run_id = make_run_id("anomaly", SEED, cfg)
    dump_json(run_dir(run_id) / "anomaly.json", out)
    write_manifest(run_id, "anomaly", "Simulated + Observed", cfg,
                   {"anomaly": "anomaly.json"}, started_at=started)
    ev = out["evaluation"]
    print(f"{run_id}: precision {ev['precision']:.2f}, recall {ev['recall']:.2f}")
    return run_id


if __name__ == "__main__":
    main()
