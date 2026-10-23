"""Bayesian marketing-mix model written directly in PyMC (no wrapper library).

EVIDENCE TYPE: Modeled.

    y_t / y_scale = intercept + controls_t · γ + Σ_c β_c · hill(adstock_c,t) + ε_t,  ε ~ N(0, σ)

- Adstock: normalised geometric, l_max = 8: a_c,t = Σ_l w_l x_c,t−l, w_l ∝ α_c^l, Σ w = 1, on
  spend scaled by the channel's mean active weekly spend. Normalisation means a constant
  spend x has steady-state adstock x, which is what the optimizer uses.
- Saturation: Hill, hill(a) = a^s / (a^s + κ^s).
- ROI parameterisation (as in Google Meridian): the prior is placed on each channel's ROI over
  the fit window, ROI_c = Σ_t contribution_c,t / Σ_t spend_c,t, and β_c is *derived*:
  β_c = ROI_c · Σ_t spend_c,t / (y_scale · Σ_t hill(a_c,t)). An ROI prior is interpretable
  and can be informed by experiments or literature; a prior on β is not.
- Optional lift-test calibration: each experiment adds a likelihood term
  Δy_obs ~ N(n_weeks · y_scale · β_c · [hill((x+Δx)/s_c) − hill(x/s_c)], σ_exp), i.e. the
  steady-state effect of the tested spend change implied by the model's response curve.

The model's functional forms deliberately differ from the simulator's (unnormalised adstock,
geo-level saturation, multiplicative seasonality, negative-binomial counts), so a good fit is
not guaranteed by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from atlas.mmm.design import L_MAX, Design

DEFAULT_ROI_PRIOR = (0.2, 0.9)  # LogNormal(mu, sigma): Meridian's default, median ROI 1.22
# Skeptical prior for demand-harvesting channels (brand search, retargeting): median 0.35,
# 90% interval ≈ [0.13, 0.94]. Motivated by published incrementality experiments on brand
# keywords and retargeting, NOT by the simulator's truth (see docs/methodology.md).
SKEPTICAL_HARVEST_PRIOR = (float(np.log(0.35)), 0.6)
HARVEST_CHANNELS = ("search_brand", "meta_retargeting")
EPS = 1e-6


@dataclass(frozen=True)
class LiftTest:
    """A lift-test result in national-equivalent units (see atlas.geolift)."""

    channel: str
    x: float  # national weekly spend level during the test (USD/week)
    delta_x: float  # tested change in weekly spend (USD/week); negative for a go-dark test
    delta_y: float  # measured incremental first-order revenue over the window (USD)
    sigma: float  # standard error of delta_y (USD)
    n_weeks: int
    source: str = ""


@dataclass(frozen=True)
class Variant:
    name: str
    label: str
    description: str
    roi_prior: dict[str, tuple[float, float]] = field(default_factory=dict)
    lift_tests: tuple[LiftTest, ...] = ()

    def prior_for(self, channel: str) -> tuple[float, float]:
        return self.roi_prior.get(channel, DEFAULT_ROI_PRIOR)


def default_variant() -> Variant:
    return Variant("bayes_default", "Bayesian MMM, default priors",
                   "ROI ~ LogNormal(0.2, 0.9) for every channel (Meridian default).")


def dag_variant() -> Variant:
    return Variant(
        "bayes_dag", "Bayesian MMM, DAG-informed harvest priors",
        "Brand search and retargeting spend is caused by demand (DAG: demand → spend → "
        "conversions), so its correlation with revenue is mostly reverse causation. Skeptical "
        "ROI prior LogNormal(log 0.35, 0.6) for those two channels; default prior elsewhere.",
        roi_prior={c: SKEPTICAL_HARVEST_PRIOR for c in HARVEST_CHANNELS})


def calibrated_variant(tests: tuple[LiftTest, ...]) -> Variant:
    base = dag_variant()
    chans = ", ".join(sorted({t.channel for t in tests}))
    return Variant("bayes_dag_calibrated", "DAG-informed MMM + lift-test calibration",
                   base.description + f" Plus a lift-test likelihood term for: {chans}.",
                   roi_prior=base.roi_prior, lift_tests=tests)


# --------------------------------------------------------------------------- PyMC model


def build_model(d: Design, variant: Variant, n_train: int | None = None):
    import pymc as pm
    import pytensor.tensor as pt

    n = n_train or len(d.weeks)
    C = len(d.channels)
    lag = d.lagged()[:, :n, :]
    mu_roi = np.array([variant.prior_for(c)[0] for c in d.channels])
    sd_roi = np.array([variant.prior_for(c)[1] for c in d.channels])
    coords = {"channel": list(d.channels), "control": list(d.control_names)}
    with pm.Model(coords=coords) as model:
        lag_d = pm.Data("lag", lag)
        y_d = pm.Data("y", d.y[:n] / d.y_scale)
        ctrl = pm.Data("ctrl", d.controls[:n])
        spend_tot = pm.Data("spend_total", d.spend[:n].sum(axis=0))
        roi_mu = pm.Data("roi_mu", mu_roi)
        roi_sd = pm.Data("roi_sd", sd_roi)

        alpha = pm.Beta("alpha", 1.5, 2.5, dims="channel")
        kappa = pm.LogNormal("kappa", 0.0, 0.7, dims="channel")
        slope = pm.LogNormal("slope", np.log(1.2), 0.25, dims="channel")
        roi = pm.LogNormal("roi", roi_mu, roi_sd, dims="channel")

        w = alpha[:, None] ** pt.arange(L_MAX)[None, :]
        w = w / w.sum(axis=1, keepdims=True)
        a = (lag_d * w[:, None, :]).sum(axis=2) + EPS  # [C, n]
        a_s = pt.exp(slope[:, None] * pt.log(a))
        k_s = pt.exp(slope * pt.log(kappa))[:, None]
        h = a_s / (a_s + k_s)
        beta = pm.Deterministic("beta", roi * spend_tot / (d.y_scale * h.sum(axis=1)),
                                dims="channel")
        media = (beta[:, None] * h).sum(axis=0)

        intercept = pm.Normal("intercept", 0.5, 0.5)
        gamma = pm.Normal("gamma", 0.0, 0.5, dims="control")
        sigma = pm.HalfNormal("sigma", 0.15)
        mu = intercept + pt.dot(ctrl, gamma) + media
        pm.Normal("obs", mu, sigma, observed=y_d)

        if variant.lift_tests:
            idx = np.array([d.channels.index(t.channel) for t in variant.lift_tests])
            x0 = np.array([t.x for t in variant.lift_tests]) / d.x_scale[idx]
            x1 = np.array([t.x + t.delta_x for t in variant.lift_tests]) / d.x_scale[idx]
            nw = np.array([t.n_weeks for t in variant.lift_tests], dtype=float)

            def _h(xv):
                xs = pt.exp(slope[idx] * pt.log(xv + EPS))
                return xs / (xs + k_s[idx, 0])

            implied = nw * beta[idx] * (_h(x1) - _h(x0))
            pm.Normal("lift", implied,
                      np.array([t.sigma for t in variant.lift_tests]) / d.y_scale,
                      observed=np.array([t.delta_y for t in variant.lift_tests]) / d.y_scale)
    assert C == len(d.channels)
    return model


# --------------------------------------------------------------------------- numpy forward


@dataclass(frozen=True)
class Posterior:
    """Flat posterior draws (numpy) plus the scales needed to use them."""

    channels: tuple[str, ...]
    control_names: tuple[str, ...]
    x_scale: np.ndarray
    y_scale: float
    alpha: np.ndarray  # [D, C]
    kappa: np.ndarray
    slope: np.ndarray
    roi: np.ndarray
    beta: np.ndarray
    intercept: np.ndarray  # [D]
    gamma: np.ndarray  # [D, K]
    sigma: np.ndarray  # [D]

    @property
    def n_draws(self) -> int:
        return self.alpha.shape[0]

    def contributions(self, d: Design) -> np.ndarray:
        """[D, C, T] media contributions in USD over the design's weeks."""
        lag = d.lagged()  # [C, T, L]
        w = self.alpha[..., None] ** np.arange(L_MAX)
        w /= w.sum(axis=-1, keepdims=True)  # [D, C, L]
        a = np.einsum("ctl,dcl->dct", lag, w) + EPS
        a_s = a ** self.slope[:, :, None]
        h = a_s / (a_s + self.kappa[:, :, None] ** self.slope[:, :, None])
        return self.beta[:, :, None] * h * self.y_scale

    def mean_prediction(self, d: Design) -> np.ndarray:
        """[D, T] expected first-order revenue in USD."""
        base = self.intercept[:, None] + self.gamma @ d.controls.T
        return base * self.y_scale + self.contributions(d).sum(axis=1)

    def weekly_response(self, channel: str, weekly_spend: np.ndarray) -> np.ndarray:
        """[D, len(spend)] steady-state weekly incremental revenue (USD) at constant spend."""
        c = self.channels.index(channel)
        x = np.asarray(weekly_spend, dtype=float)[None, :] / self.x_scale[c] + EPS
        s, k = self.slope[:, c:c + 1], self.kappa[:, c:c + 1]
        h = x**s / (x**s + k**s)
        return self.beta[:, c:c + 1] * h * self.y_scale

    def to_frame(self):
        import pandas as pd

        cols = {}
        for name in ("alpha", "kappa", "slope", "roi", "beta"):
            arr = getattr(self, name)
            for j, c in enumerate(self.channels):
                cols[f"{name}__{c}"] = arr[:, j]
        cols["intercept"] = self.intercept
        for j, k in enumerate(self.control_names):
            cols[f"gamma__{k}"] = self.gamma[:, j]
        cols["sigma"] = self.sigma
        df = pd.DataFrame(cols)
        df.insert(0, "draw", np.arange(len(df)))
        return df

    @classmethod
    def from_frame(cls, df, channels, control_names, x_scale, y_scale) -> Posterior:
        g = lambda n: np.column_stack([df[f"{n}__{c}"] for c in channels])  # noqa: E731
        return cls(channels=tuple(channels), control_names=tuple(control_names),
                   x_scale=np.asarray(x_scale, float), y_scale=float(y_scale),
                   alpha=g("alpha"), kappa=g("kappa"), slope=g("slope"), roi=g("roi"),
                   beta=g("beta"), intercept=df["intercept"].to_numpy(),
                   gamma=np.column_stack([df[f"gamma__{k}"] for k in control_names]),
                   sigma=df["sigma"].to_numpy())

    def subset(self, idx: np.ndarray) -> Posterior:
        return Posterior(self.channels, self.control_names, self.x_scale, self.y_scale,
                         self.alpha[idx], self.kappa[idx], self.slope[idx], self.roi[idx],
                         self.beta[idx], self.intercept[idx], self.gamma[idx], self.sigma[idx])
