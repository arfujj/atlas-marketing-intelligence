"""Continue a simulated world beyond its history with the TRUE data-generating process.

Used only to generate *new* data that an analyst could observe in the future (e.g. a geo-lift
experiment run after the history window). It reads the world's hidden state (adstock carry,
saturation, betas, baseline shocks), so it lives with the simulator, not with the analytics.
The extension has no promotions (none are planned in the test window) and no incidents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from atlas.sim.transforms import hill
from atlas.sim.world import BASELINE, SimulatedWorld, _calendar


@dataclass(frozen=True)
class Extension:
    weeks: pd.DatetimeIndex
    observed: pd.DataFrame  # geo × week: new_customers, first_order_revenue (recorded)
    expected: pd.DataFrame  # geo × week: expected first-order revenue (noise-free truth)


def _last_shock(world: SimulatedWorld) -> np.ndarray:
    cfg, b = world.config, world.config.baseline
    w = np.asarray(cfg.geo_weights)
    tc = world.truth_contributions
    last = tc[(tc.source == BASELINE) & (tc.week_start == tc.week_start.max())]
    base = last.set_index("geo").expected_new_customers.reindex(world.geos).to_numpy()
    cal = world.calendar.iloc[-1]
    denom = (b.new_customers_weekly * w * cal.trend_index * cal.season_index
             * (1 + b.promo_lift * float(cal.promo_week)))
    return np.log(base / denom)


def extend(world: SimulatedWorld, spend: np.ndarray, seed: int) -> Extension:
    """Simulate H post-history weeks. `spend` is effective spend [C, G, H] (USD/week)."""
    cfg, b = world.config, world.config.baseline
    C, G, H = spend.shape
    rng = np.random.default_rng([seed, 404])
    w = np.asarray(cfg.geo_weights)
    start = world.weeks[-1] + timedelta(weeks=1)
    weeks = pd.date_range(start, periods=H, freq="7D")
    cal = _calendar(weeks, cfg, np.random.default_rng(0))
    season = cal.season_index.to_numpy()
    t_idx = len(world.weeks) + np.arange(H)
    trend = (1 + b.annual_growth) ** (t_idx / 52.0)

    shock = _last_shock(world)
    shocks = np.empty((G, H))
    for h in range(H):
        shock = 0.7 * shock + rng.normal(0, 0.04, G)
        shocks[:, h] = shock
    base = b.new_customers_weekly * w[:, None] * trend * season * np.exp(shocks)

    contrib = np.zeros((C, G, H))
    for i, c in enumerate(cfg.channels):
        prev = world.adstock[i][:, -1]
        a = np.empty((G, H))
        for h in range(H):
            prev = spend[i, :, h] + c.adstock_decay * prev
            a[:, h] = prev
        contrib[i] = world.beta[i][:, None] * hill(a, world.half_saturation[i][:, None],
                                                   c.hill_slope)
    mean_by_src = np.concatenate([base[None], contrib])
    total = mean_by_src.sum(axis=0)
    r = b.nb_dispersion
    nc = rng.negative_binomial(r, r / (r + total)).astype(float)
    aov = np.array([b.first_order_aov, *[c.first_order_aov for c in cfg.channels]])
    exp_rev = (mean_by_src * aov[:, None, None]).sum(axis=0)
    rec_rev = (mean_by_src / total * nc * aov[:, None, None]).sum(axis=0) * rng.lognormal(
        0, b.aov_noise_sd, (G, H))
    gg, hh = np.meshgrid(np.arange(G), np.arange(H), indexing="ij")
    frame = lambda **cols: pd.DataFrame({  # noqa: E731
        "week_start": weeks[hh.ravel()], "geo": np.array(world.geos)[gg.ravel()],
        **{k: v.ravel() for k, v in cols.items()}})
    return Extension(weeks=weeks,
                     observed=frame(new_customers=nc, first_order_revenue=rec_rev),
                     expected=frame(first_order_revenue=exp_rev))
