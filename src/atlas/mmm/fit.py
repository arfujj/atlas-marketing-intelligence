"""Fit MMM variants, compute diagnostics and store posterior draws as runs."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.mmm.design import Design
from atlas.mmm.model import Posterior, Variant, build_model
from atlas.runs import make_run_id, run_dir, write_manifest

PARAMS = ("alpha", "kappa", "slope", "roi", "intercept", "gamma", "sigma")
HOLDOUT_WEEKS = 13
_COMPILED: dict = {}


@dataclass
class FitResult:
    variant: Variant
    posterior: Posterior
    diagnostics: dict
    n_train: int
    seconds: float


def _compile(d: Design, variant: Variant, n_train: int):
    """Compile once per model structure, then swap data (nutpie `with_data`)."""
    import nutpie

    key = (len(d.weeks), len(d.channels), n_train, len(variant.lift_tests),
           tuple(t.channel for t in variant.lift_tests))
    model = build_model(d, variant, n_train)
    if variant.lift_tests or key not in _COMPILED:
        # lift-test constants are baked into the graph, so those models are compiled fresh
        compiled = nutpie.compile_pymc_model(model, freeze_model=False)
        if not variant.lift_tests:
            _COMPILED[key] = compiled
        return compiled
    lag = d.lagged()[:, :n_train, :]
    return _COMPILED[key].with_data(
        lag=lag, y=d.y[:n_train] / d.y_scale, ctrl=d.controls[:n_train],
        spend_total=d.spend[:n_train].sum(axis=0),
        roi_mu=np.array([variant.prior_for(c)[0] for c in d.channels]),
        roi_sd=np.array([variant.prior_for(c)[1] for c in d.channels]))


def _flat(post, name: str) -> np.ndarray:
    arr = post[name].values  # (chain, draw, ...)
    return arr.reshape(-1, *arr.shape[2:])


def fit(d: Design, variant: Variant, n_train: int | None = None, draws: int = 2000,
        tune: int = 2000, chains: int = 4, seed: int = 1, keep: int = 1000,
        target_accept: float = 0.99) -> FitResult:
    import arviz as az
    import nutpie

    n_train = n_train or len(d.weeks)
    t0 = time.time()
    compiled = _compile(d, variant, n_train)
    idata = nutpie.sample(compiled, draws=draws, tune=tune, chains=chains, seed=seed,
                          progress_bar=False, save_warmup=False,
                          target_accept=target_accept)
    post = idata["posterior"]
    summ = az.summary(idata, var_names=list(PARAMS), kind="diagnostics", round_to="none")
    div = int(np.asarray(idata["sample_stats"]["diverging"].values).sum())
    total = chains * draws
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(total, size=min(keep, total), replace=False))
    p = Posterior(
        channels=d.channels, control_names=d.control_names, x_scale=d.x_scale,
        y_scale=d.y_scale, alpha=_flat(post, "alpha")[idx], kappa=_flat(post, "kappa")[idx],
        slope=_flat(post, "slope")[idx], roi=_flat(post, "roi")[idx],
        beta=_flat(post, "beta")[idx], intercept=_flat(post, "intercept")[idx],
        gamma=_flat(post, "gamma")[idx], sigma=_flat(post, "sigma")[idx])
    diag = {
        "rhat_max": float(np.nanmax(summ["r_hat"].astype(float))),
        "ess_bulk_min": float(np.nanmin(summ["ess_bulk"].astype(float))),
        "ess_tail_min": float(np.nanmin(summ["ess_tail"].astype(float))),
        "divergences": div, "draws_total": total, "chains": chains,
        "draws_kept": int(idx.size),
    }
    diag |= fit_quality(d, p, n_train, rng)
    diag["converged"] = bool(diag["rhat_max"] < 1.01 and diag["divergences"] == 0
                             and diag["ess_bulk_min"] > 400)
    return FitResult(variant, p, diag, n_train, time.time() - t0)


def fit_quality(d: Design, p: Posterior, n_train: int, rng: np.random.Generator) -> dict:
    """Posterior predictive checks on the fit window and, if any, the holdout window."""
    mu = p.mean_prediction(d)  # [D, T]
    yrep = mu + rng.normal(size=mu.shape) * (p.sigma[:, None] * d.y_scale)
    lo, hi = np.percentile(yrep, [5, 95], axis=0)
    mean = mu.mean(axis=0)

    def block(sl: slice) -> dict:
        y = d.y[sl]
        return {
            "mape": float(np.mean(np.abs(mean[sl] - y) / y)),
            "r2": float(1 - np.sum((y - mean[sl]) ** 2) / np.sum((y - y.mean()) ** 2)),
            "coverage90": float(np.mean((y >= lo[sl]) & (y <= hi[sl]))),
        }

    out = {"train": block(slice(0, n_train))}
    # Bayesian p-values of simple test statistics on the fit window (PPC)
    tr = slice(0, n_train)
    out["ppc_pvalue_sd"] = float(np.mean(yrep[:, tr].std(axis=1) >= d.y[tr].std()))
    out["ppc_pvalue_max"] = float(np.mean(yrep[:, tr].max(axis=1) >= d.y[tr].max()))
    if n_train < len(d.weeks):
        out["holdout"] = block(slice(n_train, None)) | baselines(d, n_train)
    out["ppc_band"] = {"p05": lo.tolist(), "p95": hi.tolist(), "mean": mean.tolist()}
    return out


def baselines(d: Design, n_train: int) -> dict:
    """Naive forecasts for the holdout weeks, to beat."""
    y, h = d.y, len(d.y) - n_train
    test = y[n_train:]
    trailing = np.full(h, y[n_train - 13:n_train].mean())
    # seasonal naive with growth: same week last year × trailing 13-week YoY ratio
    yoy = y[n_train - 13:n_train].sum() / y[n_train - 65:n_train - 52].sum()
    seasonal = y[n_train - 52:n_train - 52 + h] * yoy
    mape = lambda f: float(np.mean(np.abs(f - test) / test))  # noqa: E731
    return {"baseline_mape_trailing13": mape(trailing),
            "baseline_mape_seasonal_naive": mape(seasonal)}


# --------------------------------------------------------------------------- naive OLS


def ols_naive(d: Design, n_train: int | None = None) -> pd.DataFrame:
    """OLS of weekly first-order revenue on spend, intercept only, no controls.

    The coefficient is revenue per $ (ROI). Classical OLS standard errors are reported because
    they are what a naive analysis would show; they assume a correctly specified model, which
    this is not (omitted seasonality and reverse causation), so the intervals are not credible.
    """
    n = n_train or len(d.weeks)
    X = np.column_stack([np.ones(n), d.spend[:n]])
    y = d.y[:n]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    s2 = resid @ resid / (n - X.shape[1])
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))[1:]
    return pd.DataFrame({"channel": d.channels, "roi_mean": coef[1:],
                         "roi_p05": coef[1:] - 1.645 * se, "roi_p95": coef[1:] + 1.645 * se,
                         "roi_se": se})


# --------------------------------------------------------------------------- storage


def roi_summary(p: Posterior) -> pd.DataFrame:
    q = np.percentile(p.roi, [5, 50, 95], axis=0)
    return pd.DataFrame({"channel": p.channels, "roi_mean": p.roi.mean(axis=0),
                         "roi_p05": q[0], "roi_p50": q[1], "roi_p95": q[2]})


def save_fit(res: FitResult, d: Design, world: dict, seed: int, root: Path | None = None,
             tag: str | int | None = None) -> str:
    started = datetime.now(UTC)
    cfg = {"variant": res.variant.name, "n_train": res.n_train, "n_weeks": len(d.weeks),
           "seed": seed, "world": world,
           "lift_tests": [asdict(t) for t in res.variant.lift_tests],
           "roi_prior": {c: list(res.variant.prior_for(c)) for c in d.channels}}
    run_id = make_run_id("mmm", tag if tag is not None else world.get("seed", "x"), cfg)
    out = run_dir(run_id, root)
    res.posterior.to_frame().to_parquet(out / "draws.parquet", index=False)
    roi_summary(res.posterior).to_parquet(out / "roi_summary.parquet", index=False)
    diag = dict(res.diagnostics)
    (out / "diagnostics.json").write_text(json.dumps(diag, indent=1))
    hist = d.spend[: res.n_train]
    write_manifest(
        run_id, "mmm", "Modeled", cfg,
        {"draws": "draws.parquet", "roi_summary": "roi_summary.parquet",
         "diagnostics": "diagnostics.json"},
        root=root, started_at=started,
        variant_label=res.variant.label, variant_description=res.variant.description,
        channels=list(d.channels), control_names=list(d.control_names),
        x_scale=d.x_scale.tolist(), y_scale=d.y_scale,
        weeks={"start": str(d.weeks[0].date()), "end": str(d.weeks[-1].date()),
               "fit_end": str(d.weeks[res.n_train - 1].date())},
        observed_weekly_spend={c: {"min": float(hist[:, j][hist[:, j] > 0].min()),
                                   "max": float(hist[:, j].max()),
                                   "last13_mean": float(hist[-13:, j].mean())}
                               for j, c in enumerate(d.channels)},
        fit_seconds=round(res.seconds, 1),
        converged=diag["converged"])
    return run_id


def load_posterior(run_id: str, root: Path | None = None) -> tuple[Posterior, dict]:
    from atlas.runs import RUNS_DIR, read_manifest

    m = read_manifest(run_id, root)
    df = pd.read_parquet((root or RUNS_DIR) / run_id / "draws.parquet")
    return Posterior.from_frame(df, m["channels"], m["control_names"], m["x_scale"],
                                m["y_scale"]), m
