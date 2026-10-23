"""Expected value of sample information (EVSI) of candidate lift tests.

EVIDENCE TYPE: Modeled (preposterior analysis over the MMM posterior) + Assumption (economics).

For a candidate go-dark geo test on channel d with design noise σ_d (from atlas.geolift,
placebo-based, national-equivalent USD), the effect a draw θ predicts is
    e_d(θ) = n_weeks · [r_d(x_d; θ) − r_d(0; θ)] · (−1)       (lost revenue, steady state)
Preposterior analysis:
    1. draw θ_s from the current posterior and simulate y_s = e_d(θ_s) + σ_d · ε_s;
    2. importance-reweight all posterior draws by the likelihood N(y_s; e_d(θ_i), σ_d);
    3. choose the allocation that maximises the reweighted expected objective;
    4. its gain over the current-information plan a0 under the same weights, ≥ 0.
    EVSI_d = E_y[max_a E[profit | y]] − max_a E[profit] = mean gain over simulated y.
EVSI is in dollars of the chosen objective for ONE quarter's decision; it ignores the cost of
the test (lost contribution in the holdout regions while the channel is dark), which is
reported separately so the net value can be judged.
"""

from __future__ import annotations

import numpy as np

from atlas.mmm.model import Posterior
from atlas.optimizer import WEEKS, Constraints, Economics, _objective, quarterly_response, solve_dp


def _value_tables(post: Posterior, cons: Constraints, objective: str, econ: Economics):
    """Per-draw objective tables per channel: list of [D, J] arrays + lower bounds."""
    tables, lo = [], []
    for c in post.channels:
        lo_c = int(np.ceil(cons.mins.get(c, 0.0) / cons.step))
        hi_c = int(np.floor(min(cons.maxs.get(c, cons.budget), cons.budget) / cons.step))
        grid = np.arange(lo_c, hi_c + 1) * cons.step
        rev = quarterly_response(post, c, grid)  # [D, J]
        tables.append(_objective(rev, grid[None, :], objective, econ))
        lo.append(lo_c)
    return tables, lo


def _best(tables, lo, w: np.ndarray, units: int, spend_all: bool) -> tuple[list[int], float]:
    vals = [w @ t for t in tables]
    alloc = solve_dp(vals, lo, units, spend_all)
    v = sum(vals[c][alloc[c] - lo[c]] for c in range(len(alloc)))
    return alloc, float(v)


def predicted_test_effect(
    post: Posterior, channel: str, x_weekly: float, n_weeks: int
) -> np.ndarray:
    """[D] predicted incremental revenue lost by a national-equivalent go-dark test."""
    r = post.weekly_response(channel, np.array([0.0, x_weekly]))
    return -(r[:, 1] - r[:, 0]) * n_weeks


def evsi(
    post: Posterior,
    cons: Constraints,
    objective: str,
    econ: Economics,
    channel: str,
    x_weekly: float,
    sigma: float,
    n_weeks: int,
    n_sim: int = 200,
    seed: int = 0,
) -> dict:
    """Preposterior EVSI with a control variate: for each simulated outcome y the gain is
    E_w[V(a*(y))] − E_w[V(a0)] ≥ 0 under the same importance weights w(y), whose average over
    y equals E_y[max_a E[V | y]] − max_a E[V] because E_y E_w[V(a0)] = E[V(a0)]."""
    rng = np.random.default_rng(seed)
    units = int(round(cons.budget / cons.step))
    tables, lo = _value_tables(post, cons, objective, econ)
    D = post.n_draws
    a0, _ = _best(tables, lo, np.full(D, 1.0 / D), units, cons.spend_all)
    v0_draws = sum(tables[c][:, a0[c] - lo[c]] for c in range(len(a0)))  # [D]
    eff = predicted_test_effect(post, channel, x_weekly, n_weeks)
    sims = rng.choice(D, size=n_sim, replace=True)
    gains, ess, moved = [], [], []
    for s in sims:
        y = eff[s] + sigma * rng.normal()
        logw = -0.5 * ((y - eff) / sigma) ** 2
        w = np.exp(logw - logw.max())
        w /= w.sum()
        ess.append(1.0 / np.sum(w**2))
        a, v = _best(tables, lo, w, units, cons.spend_all)
        gains.append(v - float(w @ v0_draws))
        moved.append(sum(abs(x - y0) for x, y0 in zip(a, a0, strict=True)) / 2 * cons.step)
    gains = np.asarray(gains)
    moved = np.asarray(moved)
    return {
        "channel": channel,
        "evsi": float(gains.mean()),
        "evsi_mc_se": float(gains.std(ddof=1) / np.sqrt(n_sim)),
        "expected_budget_moved": float(moved.mean()),
        "prob_moves_5pct_of_budget": float(np.mean(moved >= 0.05 * cons.budget)),
        "mean_effective_sample_size": float(np.mean(ess)),
        "predicted_effect_mean": float(eff.mean()),
        "predicted_effect_p10": float(np.percentile(eff, 10)),
        "predicted_effect_p90": float(np.percentile(eff, 90)),
        "sigma": sigma,
        "n_sim": n_sim,
        "x_weekly": x_weekly,
        "n_weeks": n_weeks,
    }


def evpi(post: Posterior, cons: Constraints, objective: str, econ: Economics) -> float:
    """Expected value of perfect information: upper bound for any experiment."""
    units = int(round(cons.budget / cons.step))
    tables, lo = _value_tables(post, cons, objective, econ)
    D = post.n_draws
    _, v0 = _best(tables, lo, np.full(D, 1.0 / D), units, cons.spend_all)
    per = []
    for i in range(D):
        w = np.zeros(D)
        w[i] = 1.0
        per.append(_best(tables, lo, w, units, cons.spend_all)[1])
    return float(np.mean(per) - v0)


def experiment_cost(
    post: Posterior,
    channel: str,
    x_weekly: float,
    n_weeks: int,
    share: float,
    econ: Economics,
    objective: str,
) -> dict:
    """Expected objective value lost while the holdout regions go dark (net of saved spend)."""
    lost_rev = -predicted_test_effect(post, channel, x_weekly, n_weeks) * share
    saved = x_weekly * n_weeks * share
    vpr = econ.value_per_revenue(objective)
    cost = vpr * lost_rev - (0 if objective == "revenue" else saved)
    return {
        "expected_cost": float(cost.mean()),
        "cost_p10": float(np.percentile(cost, 10)),
        "cost_p90": float(np.percentile(cost, 90)),
        "spend_saved": float(saved),
    }


def rank_experiments(
    post: Posterior,
    cons: Constraints,
    objective: str,
    econ: Economics,
    designs: dict[str, dict],
    n_sim: int = 200,
    seed: int = 0,
) -> list[dict]:
    """designs: {channel: geolift.design_sigma(...) output}. Returns rows sorted by net value."""
    from atlas.geolift import power

    rows = []
    for k, (c, ds) in enumerate(designs.items()):
        r = evsi(
            post,
            cons,
            objective,
            econ,
            c,
            ds["x_national_weekly"],
            ds["sigma_national"],
            ds["test_weeks"],
            n_sim=n_sim,
            seed=seed + k,
        )
        cost = experiment_cost(
            post,
            c,
            ds["x_national_weekly"],
            ds["test_weeks"],
            ds["holdout_spend_share"],
            econ,
            objective,
        )
        eff = predicted_test_effect(post, c, ds["x_national_weekly"], ds["test_weeks"])
        r |= {
            "expected_test_cost": cost["expected_cost"],
            "spend_saved": cost["spend_saved"],
            "net_value": r["evsi"] - cost["expected_cost"],
            "power_at_predicted_effect": float(np.mean(power(eff, ds["sigma_national"]))),
            "design": ds,
        }
        rows.append(r)
    rows.sort(key=lambda r: -r["evsi"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


__all__ = ["WEEKS", "evpi", "evsi", "rank_experiments", "experiment_cost", "predicted_test_effect"]
