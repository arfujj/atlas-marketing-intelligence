"""Budget optimizer over stored MMM posterior draws.

EVIDENCE TYPE: Modeled (response curves) combined with Assumption (economics).

Quarterly response of channel c to quarterly spend q (13 weeks of flat spend):
    R_c(q) ≈ 13 · y_scale · β_c · hill(q / 13 / s_c)
This is the steady-state of the *normalised* adstock: under constant spend the adstocked
level equals weekly spend, so every week of the quarter contributes β·hill(x). The ramp-up at
the start of the quarter and the carryover after it are ignored; for a linear response they
cancel exactly, and with saturation the error is second order. The approximation is stated
in every result ("How was this calculated?").

Objectives (all incremental, relative to spending nothing on paid media):
    revenue              Σ R_c                       (new-customer, first-order revenue)
    profit_first_order   Σ (m · R_c − q_c)           m = contribution-margin rate
    profit_52w           Σ (m · (1 + k) · R_c − q_c) k = repeat-value multiplier (52 weeks)
m and k are ASSUMPTIONS; their defaults are estimated from observed data (first-order
contribution / first-order revenue, and trailing-52-week repeat / first-order contribution).

Solver: exact dynamic programming on a $1K grid. The objective is separable across channels
and the expectation over draws is linear, so DP over the posterior-mean curve of each channel
maximises the expected objective exactly, including for S-shaped (Hill slope > 1) curves where
gradient methods get stuck. Per-draw outcomes of the chosen plan give P10/P50/P90.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from atlas.mmm.model import Posterior

OBJECTIVES = ("revenue", "profit_first_order", "profit_52w")
OBJECTIVE_LABELS = {"revenue": "New-customer revenue",
                    "profit_first_order": "First-order contribution profit",
                    "profit_52w": "52-week contribution profit"}
WEEKS = 13


@dataclass(frozen=True)
class Economics:
    cm_rate: float  # first-order contribution margin rate (Assumption)
    repeat_multiplier: float  # 52-week repeat contribution / first-order contribution

    def value_per_revenue(self, objective: str) -> float:
        if objective == "revenue":
            return 1.0
        if objective == "profit_first_order":
            return self.cm_rate
        if objective == "profit_52w":
            return self.cm_rate * (1 + self.repeat_multiplier)
        raise ValueError(objective)


@dataclass(frozen=True)
class Constraints:
    budget: float
    mins: dict[str, float] = field(default_factory=dict)
    maxs: dict[str, float] = field(default_factory=dict)
    spend_all: bool = True
    step: float = 1_000.0


def quarterly_response(post: Posterior, channel: str, q: np.ndarray) -> np.ndarray:
    """[D, len(q)] incremental first-order revenue over a quarter of flat spend."""
    return WEEKS * post.weekly_response(channel, np.asarray(q, float) / WEEKS)


def _objective(rev: np.ndarray, q: np.ndarray, objective: str, econ: Economics) -> np.ndarray:
    v = econ.value_per_revenue(objective) * rev
    return v if objective == "revenue" else v - q


def solve_dp(values: list[np.ndarray], lo: list[int], budget_units: int,
             spend_all: bool) -> list[int]:
    """Exact DP. values[c][j] = value of spending (lo[c] + j) units on channel c."""
    C = len(values)
    neg = -np.inf
    F = np.full(budget_units + 1, neg)
    F[0] = 0.0
    choice = []
    for c in range(C):
        v, l0 = values[c], lo[c]
        J = len(v)
        G = np.full(budget_units + 1, neg)
        arg = np.zeros(budget_units + 1, dtype=int)
        for j in range(J):  # spend lo+j units on c
            s = l0 + j
            if s > budget_units:
                break
            cand = np.full(budget_units + 1, neg)
            cand[s:] = F[: budget_units + 1 - s] + v[j]
            better = cand > G
            G[better] = cand[better]
            arg[better] = s
        F = G
        choice.append(arg)
    if spend_all:
        b = budget_units
        if not np.isfinite(F[b]):
            raise ValueError("infeasible: per-channel limits cannot exactly use the budget")
    else:
        b = int(np.argmax(F))
    alloc = [0] * C
    for c in range(C - 1, -1, -1):
        s = int(choice[c][b])
        alloc[c] = s
        b -= s
    return alloc


@dataclass
class ChannelPlan:
    channel: str
    current: float
    proposed: float
    min: float
    max: float
    observed_weekly_min: float
    observed_weekly_max: float
    outside_observed_range: bool
    mroi_current: dict
    mroi_proposed: dict
    incremental_revenue_proposed: dict


@dataclass
class OptimizationResult:
    run_id: str
    objective: str
    budget: float
    spend_all: bool
    economics: dict
    channels: list[ChannelPlan]
    outcome_current: dict  # objective → {mean, p10, p50, p90}
    outcome_proposed: dict
    uplift: dict  # proposed − current, per objective
    prob_proposed_beats_current: float
    break_even_mroi: float
    n_draws: int
    explanation: str
    true: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _q(x: np.ndarray) -> dict:
    p = np.percentile(x, [10, 50, 90])
    return {"mean": float(x.mean()), "p10": float(p[0]), "p50": float(p[1]),
            "p90": float(p[2])}


def plan_outcomes(post: Posterior, plan: dict[str, float], econ: Economics) -> dict:
    """Per-draw totals for every objective of a plan: {objective: [D]}."""
    rev = sum(quarterly_response(post, c, np.array([q]))[:, 0] for c, q in plan.items())
    spend = sum(plan.values())
    return {o: _objective(rev, spend, o, econ) for o in OBJECTIVES}


def marginal_roi(post: Posterior, channel: str, q: float, step: float = 1_000.0) -> dict:
    r = quarterly_response(post, channel, np.array([q, q + step]))
    m = (r[:, 1] - r[:, 0]) / step
    return _q(m)


def optimize(post: Posterior, cons: Constraints, objective: str, econ: Economics,
             current: dict[str, float], observed: dict[str, dict], run_id: str = "") -> (
        OptimizationResult):
    if objective not in OBJECTIVES:
        raise ValueError(objective)
    chans = list(post.channels)
    units = int(round(cons.budget / cons.step))
    values, lo, his = [], [], []
    for c in chans:
        lo_c = int(np.ceil(cons.mins.get(c, 0.0) / cons.step))
        hi_c = int(np.floor(min(cons.maxs.get(c, cons.budget), cons.budget) / cons.step))
        if hi_c < lo_c:
            raise ValueError(f"{c}: max below min")
        grid = np.arange(lo_c, hi_c + 1) * cons.step
        rev = quarterly_response(post, c, grid).mean(axis=0)
        values.append(_objective(rev, grid, objective, econ))
        lo.append(lo_c)
        his.append(hi_c)
    alloc = solve_dp(values, lo, units, cons.spend_all)
    proposed = {c: a * cons.step for c, a in zip(chans, alloc, strict=True)}

    out_cur = plan_outcomes(post, current, econ)
    out_pro = plan_outcomes(post, proposed, econ)
    vpr = econ.value_per_revenue(objective)
    be = 1.0 / vpr if objective != "revenue" else float("nan")
    plans = []
    for c in chans:
        ob = observed.get(c, {})
        wk = proposed[c] / WEEKS
        outside = bool(ob) and (wk > ob["max"] * 1.0001 or (wk > 0 and wk < ob["min"]))
        plans.append(ChannelPlan(
            channel=c, current=float(current[c]), proposed=float(proposed[c]),
            min=float(cons.mins.get(c, 0.0)), max=float(cons.maxs.get(c, cons.budget)),
            observed_weekly_min=float(ob.get("min", np.nan)),
            observed_weekly_max=float(ob.get("max", np.nan)),
            outside_observed_range=outside,
            mroi_current=marginal_roi(post, c, current[c]),
            mroi_proposed=marginal_roi(post, c, proposed[c]),
            incremental_revenue_proposed=_q(
                quarterly_response(post, c, np.array([proposed[c]]))[:, 0])))
    expl = (
        f"Response curves: {post.n_draws} posterior draws of MMM run {run_id}. Quarterly "
        f"response per channel = 13 × weekly steady-state response at flat spend (normalised "
        f"adstock; ramp-up and post-quarter carryover ignored). Objective "
        f"'{OBJECTIVE_LABELS[objective]}' = "
        + ("Σ incremental first-order revenue" if objective == "revenue" else
           f"Σ ({vpr:.3f} × incremental first-order revenue − spend), where {vpr:.3f} = "
           f"contribution margin {econ.cm_rate:.3f}"
           + (f" × (1 + repeat multiplier {econ.repeat_multiplier:.3f})"
              if objective == "profit_52w" else ""))
        + f". Exact dynamic programming on a ${cons.step:,.0f} grid maximises the posterior "
        f"expected objective subject to total budget ${cons.budget:,.0f} "
        f"({'spend all' if cons.spend_all else 'underspend allowed'}) and per-channel limits. "
        "P10/P50/P90 are percentiles of the plan's outcome across posterior draws (these are "
        "the conservative / baseline / optimistic scenarios). Channels flagged 'outside observed "
        "range' would be spent at a weekly level never seen in the history: the curve there is "
        "an extrapolation.")
    return OptimizationResult(
        run_id=run_id, objective=objective, budget=cons.budget, spend_all=cons.spend_all,
        economics=asdict(econ), channels=plans,
        outcome_current={o: _q(v) for o, v in out_cur.items()},
        outcome_proposed={o: _q(v) for o, v in out_pro.items()},
        uplift={o: _q(out_pro[o] - out_cur[o]) for o in OBJECTIVES},
        prob_proposed_beats_current=float(np.mean(out_pro[objective] > out_cur[objective])),
        break_even_mroi=be, n_draws=post.n_draws, explanation=expl)


# --------------------------------------------------------------------------- sensitivity


def tornado(post: Posterior, cons: Constraints, objective: str, econ: Economics,
            current: dict[str, float], observed: dict, alt_posteriors: dict | None = None
            ) -> list[dict]:
    """One-at-a-time sensitivity of the recommendation.

    For each assumption at a low and a high value the plan is re-optimised. Reported: the
    expected objective of the re-optimised plan, its change vs the base recommendation, and
    how much budget moves between channels (half the L1 distance between allocations).
    """
    base = optimize(post, cons, objective, econ, current, observed)
    base_alloc = {p.channel: p.proposed for p in base.channels}
    base_val = base.outcome_proposed[objective]["mean"]
    cases = [
        ("Contribution margin ±20%", "cm_rate",
         (Economics(econ.cm_rate * 0.8, econ.repeat_multiplier),
          Economics(econ.cm_rate * 1.2, econ.repeat_multiplier))),
        ("Repeat-value multiplier ±50%", "repeat_multiplier",
         (Economics(econ.cm_rate, econ.repeat_multiplier * 0.5),
          Economics(econ.cm_rate, econ.repeat_multiplier * 1.5))),
    ]
    rows = []

    def _row(label, key, lo_res, hi_res):
        def shift(r):
            a = {p.channel: p.proposed for p in r.channels}
            return float(sum(abs(a[c] - base_alloc[c]) for c in a) / 2)
        rows.append({
            "assumption": label, "key": key,
            "low_value": lo_res.outcome_proposed[objective]["mean"],
            "high_value": hi_res.outcome_proposed[objective]["mean"],
            "low_delta": lo_res.outcome_proposed[objective]["mean"] - base_val,
            "high_delta": hi_res.outcome_proposed[objective]["mean"] - base_val,
            "low_budget_moved": shift(lo_res), "high_budget_moved": shift(hi_res),
            "low_allocation": {p.channel: p.proposed for p in lo_res.channels},
            "high_allocation": {p.channel: p.proposed for p in hi_res.channels},
        })

    for label, key, (e_lo, e_hi) in cases:
        _row(label, key, optimize(post, cons, objective, e_lo, current, observed),
             optimize(post, cons, objective, e_hi, current, observed))
    # Media effectiveness ±20% (all response curves scaled): a crude stand-in for model error.
    import dataclasses

    def scaled(f):
        return dataclasses.replace(post, beta=post.beta * f)

    _row("Media effectiveness ±20%", "media_scale",
         optimize(scaled(0.8), cons, objective, econ, current, observed),
         optimize(scaled(1.2), cons, objective, econ, current, observed))
    _row("Budget ±10%", "budget",
         optimize(post, dataclasses.replace(cons, budget=cons.budget * 0.9), objective, econ,
                  {c: v * 0.9 for c, v in current.items()}, observed),
         optimize(post, dataclasses.replace(cons, budget=cons.budget * 1.1), objective, econ,
                  {c: v * 1.1 for c, v in current.items()}, observed))
    for label, alt in (alt_posteriors or {}).items():
        r = optimize(alt, cons, objective, econ, current, observed)
        _row(label, "model", r, r)
    rows.sort(key=lambda r: -max(abs(r["low_delta"]), abs(r["high_delta"]),
                                 r["low_budget_moved"], r["high_budget_moved"]))
    return rows


# --------------------------------------------------------------------------- truth (sim only)


def true_evaluation(world, plans: dict[str, dict[str, float]], cons: Constraints,
                    objective: str) -> dict:
    """Grade plans in a simulated world against the TRUE optimum (atlas.sim.truth).

    The truth uses each channel's own margin and repeat value, so a plan's regret includes
    the error of the optimizer's blended economics assumptions as well as the MMM's error.
    Returns the true optimum, and for each plan its true value and regret.
    """
    from atlas.sim.truth import quarterly_curve

    chans = list(world.channels)
    units = int(round(cons.budget / cons.step))
    values, lo, curves = [], [], {}
    for c in chans:
        lo_c = int(np.ceil(cons.mins.get(c, 0.0) / cons.step))
        hi_c = int(np.floor(min(cons.maxs.get(c, cons.budget), cons.budget) / cons.step))
        grid = np.arange(lo_c, hi_c + 1) * cons.step
        vals = np.array([_true_value(o, objective) for o in quarterly_curve(world, c, grid)])
        curves[c] = (lo_c, vals)
        values.append(vals)
        lo.append(lo_c)
    alloc = solve_dp(values, lo, units, cons.spend_all)
    best = {c: a * cons.step for c, a in zip(chans, alloc, strict=True)}

    def total(plan):
        s = 0.0
        for c, q in plan.items():
            lo_c, vals = curves[c]
            j = int(round(q / cons.step)) - lo_c
            if 0 <= j < len(vals):
                s += vals[j]
            else:  # outside the constraint grid: evaluate directly
                s += _true_value(quarterly_curve(world, c, np.array([q]))[0], objective)
        return s

    v_best = total(best)
    out = {"objective": objective, "true_optimum": best, "true_value_optimum": v_best,
           "plans": {}}
    for name, plan in plans.items():
        v = total(plan)
        out["plans"][name] = {"true_value": v, "regret": v_best - v}
    return out


def _true_value(o, objective: str) -> float:
    if objective == "revenue":
        return o.first_order_revenue
    if objective == "profit_first_order":
        return o.profit_first_order
    return o.profit_ltv52
