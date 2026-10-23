"""Statistics used in the Criteo readout, checked on synthetic data with a known answer
(the real file is never needed for tests)."""

from __future__ import annotations

import numpy as np
import pytest

from atlas.criteo import (
    cace,
    evaluate_uplift,
    fit_uplift,
    mde,
    qini_coefficient,
    qini_curve,
    rank_order,
    required_n,
    srm_test,
    two_proportion,
)


def test_srm_passes_on_exact_ratio_and_flags_mismatch():
    assert not srm_test(850_000, 150_000)["srm_detected"]
    assert srm_test(853_000, 147_000)["srm_detected"]


def test_two_proportion_ci_covers_truth():
    rng = np.random.default_rng(0)
    hits = 0
    for _ in range(200):
        yt = rng.random(20_000) < 0.06
        yc = rng.random(5_000) < 0.05
        r = two_proportion(yt.astype(float), yc.astype(float))
        hits += r["abs_lift_ci95"][0] <= 0.01 <= r["abs_lift_ci95"][1]
    assert 0.90 <= hits / 200 <= 0.99


def test_cace_recovers_complier_effect_and_naive_is_biased():
    rng = np.random.default_rng(1)
    n = 400_000
    z = (rng.random(n) < 0.85).astype(float)
    propensity_type = rng.random(n)  # latent: high-intent users are more likely to be exposed
    complier = propensity_type < 0.3
    d = z * complier
    base = 0.02 + 0.08 * (propensity_type < 0.3)  # compliers have higher baseline
    y = (rng.random(n) < base + 0.05 * d).astype(float)
    r = cace(y, d, z)
    assert r["exposure_rate_control"] == 0
    assert r["cace_ci95"][0] <= 0.05 <= r["cace_ci95"][1]
    assert r["naive_exposed_vs_control"] > r["cace"] + 0.03  # selection bias
    assert r["complier_baseline_rate"] == pytest.approx(0.10, abs=0.01)


def test_mde_and_required_n_are_consistent():
    n = required_n(0.05, 0.10, treat_share=0.5)
    n_t = n_c = n // 2
    assert mde(0.05, n_t, n_c) == pytest.approx(0.005, rel=0.02)


def test_qini_perfect_score_beats_random():
    rng = np.random.default_rng(2)
    n = 50_000
    x = rng.normal(size=(n, 3))
    t = (rng.random(n) < 0.5).astype(float)
    tau = 0.1 * (x[:, 0] > 0)
    y = (rng.random(n) < 0.05 + tau * t).astype(float)
    frac, q_oracle = qini_curve(tau + rng.normal(0, 1e-6, n), t, y)
    _, q_rand = qini_curve(rng.random(n), t, y)
    assert qini_coefficient(frac, q_oracle) > qini_coefficient(frac, q_rand) + 0.005
    models = fit_uplift(x, t, y, seed=0, propensity=0.5)
    ev = evaluate_uplift(models, x, t, y, n_boot=20, seed=0)
    for learner in ("s_learner", "t_learner", "x_learner"):
        assert ev[learner]["qini_coefficient_ci95"][0] > ev["random"]["qini_coefficient"]


def test_tied_scores_do_not_bend_the_qini_curve_when_input_is_sorted_by_treatment():
    # Constant score = no targeting information, so the curve must follow the random line,
    # even though the input lists every treated user before every control user.
    rng = np.random.default_rng(3)
    n = 40_000
    t = np.r_[np.ones(n // 2), np.zeros(n // 2)]
    y = (rng.random(n) < 0.05 + 0.02 * t).astype(float)
    score = np.zeros(n)
    frac, q = qini_curve(score, t, y, order=rank_order(score, rng))
    _, q_stable = qini_curve(score, t, y)  # input order: the failure this guards against

    def max_gap(curve):  # largest distance from the random-targeting line
        return float(np.max(np.abs(curve - frac * curve[-1])))

    assert max_gap(q) < 0.1 * q[-1]
    assert max_gap(q_stable) > 0.3 * q_stable[-1]
