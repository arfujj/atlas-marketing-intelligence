"""Criteo Uplift v2.1 readout: a real randomized incrementality test.

EVIDENCE TYPE: Experimental (observed RCT). Data: Criteo AI Lab, "A Large Scale Benchmark for
Uplift Modeling" (Diemert et al., 2018), v2.1, ~13.98M users, treatment ratio 85/15, licensed
CC BY-NC-SA 4.0. The raw file is downloaded by `python -m atlas.criteo download` into
data/raw/ (gitignored) and never committed; only aggregated results are written to
model_runs/criteo-*/.

The data has no spend, revenue or channel and comes from a different company than anything else
in ATLAS. It is never joined with GA4 or Halden data.

Analyses
- Sample-ratio mismatch (chi-square against the documented 85% treatment ratio).
- Intent-to-treat (ITT) absolute and relative lift on visit and conversion, 95% CIs.
- Complier average causal effect (CACE) on exposed users via the Wald / IV estimator with
  assignment as the instrument for exposure. Assumptions: (1) exclusion restriction:
  assignment affects outcomes only through exposure; (2) one-sided non-compliance: control
  users cannot be exposed (checked in the data); (3) SUTVA / no interference between users;
  (4) instrument relevance (first stage far from zero).
- Power and minimum detectable effect.
- S-, T- and X-learner uplift models (HistGradientBoosting) trained on a subsample of the
  training split and evaluated on held-out users with Qini curves and a bootstrap CI for the
  Qini coefficient, against random targeting.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from atlas.runs import ROOT, make_run_id, run_dir, write_manifest

URL = ("https://huggingface.co/datasets/criteo/criteo-uplift/resolve/main/"
       "criteo-research-uplift-v2.1.csv.gz")
RAW = ROOT / "data" / "raw" / "criteo" / "criteo-research-uplift-v2.1.csv.gz"
FEATURES = [f"f{i}" for i in range(12)]
DOCUMENTED_TREATMENT_RATIO = 0.85
Z95 = stats.norm.ppf(0.975)


# --------------------------------------------------------------------------- data


def download(dest: Path = RAW) -> Path:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(URL, tmp)  # noqa: S310 - fixed https URL
    tmp.rename(dest)
    return dest


def load(path: Path = RAW) -> pd.DataFrame:
    import pyarrow as pa
    import pyarrow.csv as pacsv

    types = {f: pa.float32() for f in FEATURES} | {
        c: pa.int8() for c in ("treatment", "conversion", "visit", "exposure")}
    tbl = pacsv.read_csv(path, convert_options=pacsv.ConvertOptions(column_types=types))
    return tbl.to_pandas()


# --------------------------------------------------------------------------- statistics


def srm_test(n_t: int, n_c: int, expected_ratio: float = DOCUMENTED_TREATMENT_RATIO) -> dict:
    n = n_t + n_c
    exp = np.array([n * expected_ratio, n * (1 - expected_ratio)])
    chi2, p = stats.chisquare([n_t, n_c], exp)
    return {"n_treatment": int(n_t), "n_control": int(n_c),
            "observed_ratio": n_t / n, "expected_ratio": expected_ratio,
            "chi2": float(chi2), "p_value": float(p),
            "srm_detected": bool(p < 0.001)}


def two_proportion(y_t: np.ndarray, y_c: np.ndarray) -> dict:
    n_t, n_c = y_t.size, y_c.size
    p_t, p_c = y_t.mean(), y_c.mean()
    diff = p_t - p_c
    se = np.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
    pooled = (y_t.sum() + y_c.sum()) / (n_t + n_c)
    se0 = np.sqrt(pooled * (1 - pooled) * (1 / n_t + 1 / n_c))
    z = diff / se0
    rel = p_t / p_c - 1
    se_log = np.sqrt((1 - p_t) / (n_t * p_t) + (1 - p_c) / (n_c * p_c))
    lo, hi = np.exp(np.log(p_t / p_c) + np.array([-1, 1]) * Z95 * se_log) - 1
    return {"rate_treatment": float(p_t), "rate_control": float(p_c),
            "abs_lift": float(diff), "abs_lift_ci95": [float(diff - Z95 * se),
                                                       float(diff + Z95 * se)],
            "rel_lift": float(rel), "rel_lift_ci95": [float(lo), float(hi)],
            "z": float(z), "p_value": float(2 * stats.norm.sf(abs(z)))}


def cace(y: np.ndarray, d: np.ndarray, z: np.ndarray) -> dict:
    """Wald / IV estimate of the effect of exposure d on outcome y, instrument z (assignment).

    Delta-method SE using within-arm covariance of (y, d).
    """
    t, c = z == 1, z == 0
    itt_y = y[t].mean() - y[c].mean()
    itt_d = d[t].mean() - d[c].mean()
    est = itt_y / itt_d
    var_y = y[t].var() / t.sum() + y[c].var() / c.sum()
    var_d = d[t].var() / t.sum() + d[c].var() / c.sum()
    cov = (np.cov(y[t], d[t])[0, 1] / t.sum()) + (np.cov(y[c], d[c])[0, 1] / c.sum())
    se = np.sqrt((var_y + est**2 * var_d - 2 * est * cov) / itt_d**2)
    exposed_t = (d == 1) & t
    naive = y[exposed_t].mean() - y[c].mean()
    # Complier baseline: in the control arm compliers are not identified individually, but
    # E[Y0 | complier] = (E[Y | z=0] - (1-π) E[Y | z=1, d=0]) / π under one-sided non-compliance.
    pi = d[t].mean()
    y0_compliers = (y[c].mean() - (1 - pi) * y[t & (d == 0)].mean()) / pi
    return {"first_stage_exposure_rate_treatment": float(d[t].mean()),
            "exposure_rate_control": float(d[c].mean()),
            "itt_outcome": float(itt_y), "itt_exposure": float(itt_d),
            "cace": float(est), "cace_ci95": [float(est - Z95 * se), float(est + Z95 * se)],
            "complier_baseline_rate": float(y0_compliers),
            "cace_rel_lift": float(est / y0_compliers) if y0_compliers > 0 else None,
            "naive_exposed_vs_control": float(naive),
            "naive_bias_vs_cace": float(naive - est)}


def mde(p: float, n_t: int, n_c: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Minimum detectable absolute lift for a two-sided two-proportion test."""
    k = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(k * np.sqrt(p * (1 - p) * (1 / n_t + 1 / n_c)))


def required_n(p: float, rel_lift: float, treat_share: float = 0.85, alpha: float = 0.05,
               power: float = 0.8) -> int:
    k = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    delta = p * rel_lift
    var = p * (1 - p) * (1 / treat_share + 1 / (1 - treat_share))
    return int(np.ceil(var * (k / delta) ** 2))


# --------------------------------------------------------------------------- uplift


def _hgb(kind: str, seed: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

    cls = HistGradientBoostingClassifier if kind == "clf" else HistGradientBoostingRegressor
    return cls(max_iter=200, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=200,
               l2_regularization=1.0, early_stopping=True, validation_fraction=0.1,
               random_state=seed)


def fit_uplift(x: np.ndarray, t: np.ndarray, y: np.ndarray, seed: int,
               propensity: float) -> dict:
    """Returns {learner: callable(X) -> predicted uplift}."""
    # S-learner: one model with treatment as a feature.
    s = _hgb("clf", seed).fit(np.column_stack([x, t]), y)

    def s_pred(xx):
        one, zero = np.ones((len(xx), 1)), np.zeros((len(xx), 1))
        return (s.predict_proba(np.column_stack([xx, one]))[:, 1]
                - s.predict_proba(np.column_stack([xx, zero]))[:, 1])

    m1 = _hgb("clf", seed).fit(x[t == 1], y[t == 1])
    m0 = _hgb("clf", seed).fit(x[t == 0], y[t == 0])

    def t_pred(xx):
        return m1.predict_proba(xx)[:, 1] - m0.predict_proba(xx)[:, 1]

    # X-learner with the known randomization propensity.
    d1 = y[t == 1] - m0.predict_proba(x[t == 1])[:, 1]
    d0 = m1.predict_proba(x[t == 0])[:, 1] - y[t == 0]
    tau1 = _hgb("reg", seed).fit(x[t == 1], d1)
    tau0 = _hgb("reg", seed).fit(x[t == 0], d0)

    def x_pred(xx):
        return propensity * tau0.predict(xx) + (1 - propensity) * tau1.predict(xx)

    return {"s_learner": s_pred, "t_learner": t_pred, "x_learner": x_pred}


def qini_curve(score: np.ndarray, t: np.ndarray, y: np.ndarray, n_points: int = 101,
               weights: np.ndarray | None = None,
               order: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Qini curve: incremental outcomes when targeting the top fraction by score.

    Q(k) = Y_t(k) − Y_c(k) · N_t(k) / N_c(k), normalised by the total number of users so it reads
    as "incremental outcomes per user in the population". Returns (fractions, Q).
    """
    if order is None:
        order = np.argsort(-score, kind="stable")
    w = np.ones_like(score, dtype=float) if weights is None else weights
    tw, cw = (t[order] * w[order]), ((1 - t[order]) * w[order])
    nt, nc = np.cumsum(tw), np.cumsum(cw)
    yt, yc = np.cumsum(tw * y[order]), np.cumsum(cw * y[order])
    n = nt[-1] + nc[-1]
    idx = np.clip((np.linspace(0, 1, n_points) * len(score)).astype(int) - 1, 0, len(score) - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = np.where(nc[idx] > 0, yt[idx] - yc[idx] * nt[idx] / nc[idx], 0.0) / n
    q[0] = 0.0
    return np.linspace(0, 1, n_points), q


def qini_coefficient(frac: np.ndarray, q: np.ndarray) -> float:
    """Area between the Qini curve and the random-targeting line (same end point)."""
    random_line = frac * q[-1]
    return float(np.trapezoid(q - random_line, frac))


def rank_order(score: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Descending score order with ties broken at random.

    A stable sort would keep tied users in input order; if the input is grouped by treatment,
    a block of tied scores then comes out treated-first and bends the Qini curve (seen with
    the X-learner, whose regression trees produce large tie blocks)."""
    return np.lexsort((rng.random(len(score)), -score))


def uplift_at(score: np.ndarray, t: np.ndarray, y: np.ndarray, top: float,
              order: np.ndarray | None = None) -> float:
    k = int(len(score) * top)
    sel = (np.argsort(-score, kind="stable") if order is None else order)[:k]
    tt, yy = t[sel], y[sel]
    return float(yy[tt == 1].mean() - yy[tt == 0].mean())


def evaluate_uplift(models: dict, x: np.ndarray, t: np.ndarray, y: np.ndarray,
                    n_boot: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    scores = {name: f(x) for name, f in models.items()}
    scores["random"] = rng.random(len(x))
    orders = {name: rank_order(sc, rng) for name, sc in scores.items()}
    boot_coefs: dict[str, list[float]] = {name: [] for name in scores}
    for _ in range(n_boot):  # Poisson bootstrap: one weight vector shared by all learners
        wb = rng.poisson(1.0, size=len(x)).astype(np.float64)
        for name, sc in scores.items():
            fb, qb = qini_curve(sc, t, y, weights=wb, order=orders[name])
            boot_coefs[name].append(qini_coefficient(fb, qb))
    for name, sc in scores.items():
        frac, q = qini_curve(sc, t, y, order=orders[name])
        coef = qini_coefficient(frac, q)
        bs = boot_coefs[name]
        out[name] = {
            "qini_coefficient": coef,
            "qini_coefficient_ci95": ([float(np.percentile(bs, 2.5)),
                                       float(np.percentile(bs, 97.5))] if bs else None),
            "uplift_top10": uplift_at(sc, t, y, 0.10, orders[name]),
            "uplift_top20": uplift_at(sc, t, y, 0.20, orders[name]),
            "uplift_top30": uplift_at(sc, t, y, 0.30, orders[name]),
            "curve": {"fraction": frac.round(4).tolist(), "qini": q.tolist()},
        }
    return out


# --------------------------------------------------------------------------- job


def run(seed: int = 20261023, train_rows: int = 2_000_000, test_frac: float = 0.3,
        eval_rows: int = 2_000_000, n_boot: int = 200, path: Path = RAW) -> str:
    started = datetime.now(UTC)
    t0 = time.time()
    df = load(path)
    n = len(df)
    t = df.treatment.to_numpy()
    res: dict = {"n_rows": n, "license": "CC BY-NC-SA 4.0 (Criteo AI Lab)",
                 "source": URL}
    res["srm"] = srm_test(int(t.sum()), int(n - t.sum()))
    res["itt"] = {o: two_proportion(df[o].to_numpy()[t == 1].astype(float),
                                    df[o].to_numpy()[t == 0].astype(float))
                  for o in ("visit", "conversion")}
    d = df.exposure.to_numpy().astype(float)
    res["cace"] = {o: cace(df[o].to_numpy().astype(float), d, t) for o in ("visit", "conversion")}
    n_t, n_c = int(t.sum()), int(n - t.sum())
    res["power"] = {
        o: {"baseline_rate": res["itt"][o]["rate_control"],
            "mde_abs_80pct": mde(res["itt"][o]["rate_control"], n_t, n_c),
            "mde_rel_80pct": mde(res["itt"][o]["rate_control"], n_t, n_c)
            / res["itt"][o]["rate_control"],
            "observed_abs_lift": res["itt"][o]["abs_lift"],
            "n_required_for_observed_rel_lift": required_n(
                res["itt"][o]["rate_control"], res["itt"][o]["rel_lift"]),
            "n_required_for_5pct_rel_lift": required_n(res["itt"][o]["rate_control"], 0.05),
            } for o in ("visit", "conversion")}
    print(f"[criteo] stats done in {time.time() - t0:.0f}s", flush=True)

    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    n_test = int(n * test_frac)
    test_idx, train_pool = perm[:n_test], perm[n_test:]
    tr = np.sort(train_pool[:train_rows])
    te = np.sort(test_idx[:eval_rows])
    x = df[FEATURES].to_numpy()
    res["uplift"] = {"train_rows": int(tr.size), "eval_rows": int(te.size),
                     "test_split_rows": int(n_test), "n_bootstrap": n_boot,
                     "model": "HistGradientBoosting (max_iter=200, lr=0.08, 31 leaves, "
                              "min_samples_leaf=200, early stopping)",
                     "outcomes": {}}
    for o in ("visit", "conversion"):
        y = df[o].to_numpy()
        models = fit_uplift(x[tr], t[tr], y[tr].astype(float), seed, DOCUMENTED_TREATMENT_RATIO)
        ev = evaluate_uplift(models, x[te], t[te].astype(float), y[te].astype(float),
                             n_boot, seed)
        ev["itt_eval_set"] = float(y[te][t[te] == 1].mean() - y[te][t[te] == 0].mean())
        res["uplift"]["outcomes"][o] = ev
        print(f"[criteo] uplift {o} done in {time.time() - t0:.0f}s", flush=True)

    cfg = {"seed": seed, "train_rows": train_rows, "test_frac": test_frac,
           "eval_rows": eval_rows, "n_boot": n_boot, "n_rows": n}
    run_id = make_run_id("criteo", seed, cfg)
    out = run_dir(run_id)
    (out / "readout.json").write_text(json.dumps(res, indent=2))
    write_manifest(run_id, "criteo", "Experimental", cfg, {"readout": "readout.json"},
                   started_at=started,
                   note="Aggregated results only; raw Criteo rows are never committed.")
    print(run_id)
    return run_id


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="atlas.criteo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    r = sub.add_parser("run")
    r.add_argument("--seed", type=int, default=20261023)
    r.add_argument("--train-rows", type=int, default=2_000_000)
    r.add_argument("--eval-rows", type=int, default=2_000_000)
    r.add_argument("--n-boot", type=int, default=200)
    r.add_argument("--delete-raw", action="store_true",
                   help="delete the raw file after a successful run (disk budget)")
    a = p.parse_args(argv)
    if a.cmd == "download":
        print(download())
    else:
        download()
        run(a.seed, a.train_rows, eval_rows=a.eval_rows, n_boot=a.n_boot)
        if a.delete_raw:
            RAW.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
