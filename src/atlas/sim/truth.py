"""Ground-truth response functions of a simulated world.

Used ONLY to grade estimates (attribution, MMM, optimizer recommendations). Nothing in
the serving path that a "real" analyst would have access to may call this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from atlas.sim.transforms import hill
from atlas.sim.world import SimulatedWorld

CARRYOVER_TAIL_WEEKS = 26


@dataclass(frozen=True)
class IncrementalOutcome:
    spend: float
    new_customers: float
    first_order_revenue: float
    first_order_contribution: float
    ltv52_revenue: float
    ltv52_contribution: float

    @property
    def profit_first_order(self) -> float:
        return self.first_order_contribution - self.spend

    @property
    def profit_ltv52(self) -> float:
        return self.first_order_contribution + self.ltv52_contribution - self.spend


def incremental_outcome(world: SimulatedWorld, channel: str, weekly_spend: np.ndarray,
                        promo_weeks: np.ndarray | None = None) -> IncrementalOutcome:
    """True expected effect of spending `weekly_spend` (national, USD/week) after history.

    Counterfactual: the same channel spends 0 over the plan. Carryover from historical
    spend is included in both arms, so the result is the plan's own increment, counting
    a 26-week post-plan adstock tail. Spend is split across geos by population weight.
    """
    i = world.channels.index(channel)
    c = world.config.channels[i]
    b = world.config.baseline
    w = np.asarray(world.config.geo_weights)
    x = np.asarray(weekly_spend, dtype=float)
    if np.any(x < 0):
        raise ValueError("spend must be non-negative")
    h = x.size
    promo = np.zeros(h + CARRYOVER_TAIL_WEEKS) if promo_weeks is None else np.concatenate(
        [np.asarray(promo_weeks, float), np.zeros(CARRYOVER_TAIL_WEEKS)])
    plan = np.concatenate([x, np.zeros(CARRYOVER_TAIL_WEEKS)])[None, :] * w[:, None]

    carry = world.adstock[i][:, -1]
    k = np.arange(plan.shape[1])
    a0 = carry[:, None] * c.adstock_decay ** (k + 1)  # history carryover only
    a1 = np.empty_like(plan)
    prev = carry
    for t in range(plan.shape[1]):
        prev = plan[:, t] + c.adstock_decay * prev
        a1[:, t] = prev
    K = world.half_saturation[i][:, None]
    inc_new = world.beta[i][:, None] * (hill(a1, K, c.hill_slope) - hill(a0, K, c.hill_slope))
    d = b.promo_discount * promo[None, :]
    n = inc_new.sum()
    return IncrementalOutcome(
        spend=float(x.sum()),
        new_customers=float(n),
        first_order_revenue=float((inc_new * c.first_order_aov * (1 - d)).sum()),
        first_order_contribution=float(
            (inc_new * c.first_order_aov * (c.first_order_cm_rate - d)).sum()),
        ltv52_revenue=float(n * c.repeat_revenue_52w),
        ltv52_contribution=float(n * c.repeat_revenue_52w * b.repeat_cm_rate),
    )


def quarterly_curve(world: SimulatedWorld, channel: str, quarterly_spend: np.ndarray,
                    weeks: int = 13) -> list[IncrementalOutcome]:
    """True response to flat weekly spend across a quarter, for each total in the grid."""
    return [incremental_outcome(world, channel, np.full(weeks, s / weeks))
            for s in np.asarray(quarterly_spend, dtype=float)]


def marginal_roi(world: SimulatedWorld, channel: str, quarterly_spend: float,
                 step: float = 1_000.0, weeks: int = 13) -> dict[str, float]:
    """Incremental first-order revenue and LTV-52 contribution of the next `step` dollars."""
    lo, hi = quarterly_curve(world, channel, np.array([quarterly_spend, quarterly_spend + step]),
                             weeks)
    return {
        "mroi_first_order_revenue": (hi.first_order_revenue - lo.first_order_revenue) / step,
        "mroi_first_order_contribution":
            (hi.first_order_contribution - lo.first_order_contribution) / step,
        "mroi_ltv52_contribution": (
            (hi.first_order_contribution + hi.ltv52_contribution)
            - (lo.first_order_contribution + lo.ltv52_contribution)) / step,
    }
