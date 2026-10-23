"""Optimizer, value of information and geo-lift: property and correctness tests.

Posteriors here are synthetic (hand-built draws), so the tests are fast and the right answer
is known."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atlas.geolift import GeoDesign, power, ratio_effect, run_geolift
from atlas.mmm.model import Posterior
from atlas.optimizer import (
    Constraints,
    Economics,
    optimize,
    quarterly_response,
    solve_dp,
    tornado,
)
from atlas.voi import evsi, predicted_test_effect

CH = ("a", "b", "c")


def toy_posterior(n=200, seed=0, slope=(1.0, 2.5, 1.0), roi_sd=0.3) -> Posterior:
    rng = np.random.default_rng(seed)
    C = len(CH)
    beta = np.exp(rng.normal(np.log([0.3, 0.4, 0.15]), roi_sd, (n, C)))
    return Posterior(
        channels=CH, control_names=("trend",), x_scale=np.array([10_000.0, 10_000.0, 10_000.0]),
        y_scale=100_000.0, alpha=np.full((n, C), 0.3), kappa=np.ones((n, C)),
        slope=np.tile(np.array(slope), (n, 1)), roi=np.ones((n, C)), beta=beta,
        intercept=np.ones(n), gamma=np.zeros((n, 1)), sigma=np.full(n, 0.05))


ECON = Economics(cm_rate=0.4, repeat_multiplier=1.0)
OBS = {c: {"min": 5_000.0, "max": 15_000.0} for c in CH}


def brute_force(post, cons, objective):
    best, arg = -np.inf, None
    grids = [np.arange(cons.mins.get(c, 0), cons.maxs.get(c, cons.budget) + 1, cons.step)
             for c in CH]
    for combo in itertools.product(*grids):
        if cons.spend_all and abs(sum(combo) - cons.budget) > 1e-6:
            continue
        if sum(combo) > cons.budget + 1e-6:
            continue
        v = sum(ECON.value_per_revenue(objective)
                * quarterly_response(post, c, np.array([q])).mean() - (
                    q if objective != "revenue" else 0) for c, q in zip(CH, combo, strict=True))
        if v > best:
            best, arg = v, combo
    return dict(zip(CH, arg, strict=True)), best


@pytest.mark.parametrize("objective", ["revenue", "profit_52w"])
@pytest.mark.parametrize("spend_all", [True, False])
def test_dp_matches_brute_force_including_s_curves(objective, spend_all):
    post = toy_posterior()
    cons = Constraints(budget=300_000, mins={"a": 20_000}, maxs={"c": 120_000},
                       spend_all=spend_all, step=20_000)
    r = optimize(post, cons, objective, ECON, {c: 100_000 for c in CH}, OBS)
    got = {p.channel: p.proposed for p in r.channels}
    want, _ = brute_force(post, cons, objective)
    assert got == want


@settings(max_examples=40, deadline=None)
@given(budget=st.integers(5, 40), lo=st.lists(st.integers(0, 5), min_size=3, max_size=3),
       width=st.lists(st.integers(3, 30), min_size=3, max_size=3),
       spend_all=st.booleans())
def test_constraints_always_hold(budget, lo, width, spend_all):
    hi = [a + w for a, w in zip(lo, width, strict=True)]
    rng = np.random.default_rng(budget)
    values = [np.cumsum(rng.random(h - a + 1)) for a, h in zip(lo, hi, strict=True)]
    if spend_all and not (sum(lo) <= budget <= sum(hi)):
        with pytest.raises(ValueError):
            solve_dp(values, lo, budget, spend_all)
        return
    if sum(lo) > budget:
        return
    alloc = solve_dp(values, lo, budget, spend_all)
    assert all(a <= x <= h for a, x, h in zip(lo, alloc, hi, strict=True))
    assert sum(alloc) <= budget
    if spend_all:
        assert sum(alloc) == budget


def test_result_reports_uncertainty_and_guardrails():
    post = toy_posterior()
    cons = Constraints(budget=300_000, step=1_000)
    r = optimize(post, cons, "profit_52w", ECON, {c: 100_000 for c in CH}, OBS)
    out = r.outcome_proposed["profit_52w"]
    assert out["p10"] <= out["p50"] <= out["p90"]
    assert 0 <= r.prob_proposed_beats_current <= 1
    # expected objective of the proposal is at least that of the current plan
    assert out["mean"] >= r.outcome_current["profit_52w"]["mean"] - 1e-6
    assert any(p.outside_observed_range for p in r.channels if p.proposed / 13 > 15_000)
    assert "posterior draws" in r.explanation


def test_tornado_rows_have_both_sides():
    post = toy_posterior()
    cons = Constraints(budget=300_000, step=5_000)
    rows = tornado(post, cons, "profit_52w", ECON, {c: 100_000 for c in CH}, OBS)
    assert {r["key"] for r in rows} >= {"cm_rate", "repeat_multiplier", "media_scale",
                                        "budget"}
    cm = next(r for r in rows if r["key"] == "cm_rate")
    assert cm["low_delta"] < 0 < cm["high_delta"]


def test_evsi_nonnegative_and_grows_with_precision():
    post = toy_posterior(n=300, roi_sd=0.6)
    cons = Constraints(budget=300_000, step=10_000)
    noisy = evsi(post, cons, "profit_52w", ECON, "b", 10_000, sigma=2e6, n_weeks=6, n_sim=60)
    sharp = evsi(post, cons, "profit_52w", ECON, "b", 10_000, sigma=2e3, n_weeks=6, n_sim=60)
    assert noisy["evsi"] >= -1e-9 and sharp["evsi"] >= -1e-9
    assert sharp["evsi"] > noisy["evsi"]
    eff = predicted_test_effect(post, "b", 10_000, 6)
    assert np.all(eff < 0)


def test_power_is_alpha_at_zero_and_increases():
    assert power(0.0, 1.0) == pytest.approx(0.10)
    assert power(3.0, 1.0) > power(1.0, 1.0) > power(0.0, 1.0)


def test_ratio_estimator_is_exact_without_noise():
    import pandas as pd

    y = pd.DataFrame(np.tile(np.array([[10.0], [20.0], [30.0]]), (1, 10)),
                     index=["g1", "g2", "g3"])
    y.iloc[0, 6:] -= 2.0  # treated region loses 2 per week in the last 4 weeks
    dy, cf = ratio_effect(y, ("g1",), slice(0, 6), slice(6, 10))
    assert dy == pytest.approx(-8.0)
    assert cf == pytest.approx(40.0)


def test_geolift_readout_on_halden(halden_world):
    from atlas.geolift import stratified_holdout

    ho = stratified_holdout(list(halden_world.geos), list(halden_world.config.geo_weights),
                            seed=1)
    assert len(ho) == 3 and all(isinstance(g, str) for g in ho)
    r = run_geolift(halden_world, GeoDesign("meta_prospecting", ho, ()), seed=3)
    assert r.true_delta_y < 0  # going dark on a positive-ROI channel loses revenue
    assert r.se > 0 and r.ci90[0] < r.delta_y < r.ci90[1]
    assert r.lift_test.delta_x == pytest.approx(-r.x_national_weekly)
    assert 0.2 < r.holdout_spend_share < 0.6
