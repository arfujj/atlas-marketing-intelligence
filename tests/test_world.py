import numpy as np
import pandas as pd
import pytest

from atlas.sim import default_world, simulate
from atlas.sim.truth import incremental_outcome, marginal_roi, quarterly_curve


@pytest.fixture(scope="module")
def world():
    return simulate(default_world(), seed=7)


def test_deterministic_given_seed(world):
    again = simulate(default_world(), seed=7)
    pd.testing.assert_frame_equal(world.outcomes, again.outcomes)
    pd.testing.assert_frame_equal(world.media, again.media)


def test_different_seeds_differ(world):
    other = simulate(default_world(), seed=8)
    assert not np.allclose(world.outcomes.revenue, other.outcomes.revenue)


def test_grain_is_unique(world):
    assert not world.media.duplicated(["week_start", "geo", "channel"]).any()
    assert not world.outcomes.duplicated(["week_start", "geo"]).any()
    cfg = world.config
    assert len(world.outcomes) == cfg.n_weeks * cfg.n_geos


def test_no_negative_or_missing_values(world):
    for df in (world.media, world.outcomes, world.truth_contributions):
        assert not df.isna().any().any()
    num = world.media.select_dtypes("number")
    assert (num >= 0).all().all()
    assert (world.outcomes[["new_customers", "revenue", "orders"]] >= 0).all().all()


def test_spend_matches_budget(world):
    """Effective spend hits the budget; billed spend differs only by the CPC-spike inflation."""
    H = np.s_[world.burn_in:]
    for i, c in enumerate(world.config.channels):
        effective = world.spend[i][:, H].sum()
        expected = c.annual_spend * (world.config.n_weeks - c.launch_week) / 52
        assert effective == pytest.approx(expected, rel=1e-9)
        billed = world.media.loc[world.media.channel == c.name, "spend"].sum()
        assert billed == pytest.approx(world.billed_spend[i][:, H].sum(), rel=1e-9)
        if c.name != "search_nonbrand":
            assert billed == pytest.approx(expected, rel=1e-9)


def test_launch_week_respected(world):
    tk = world.media[world.media.channel == "tiktok"].sort_values("week_start")
    first = tk.loc[tk.spend > 0, "week_start"].min()
    assert first == world.weeks[world.burn_in + 40]


def test_true_roi_is_calibrated(world):
    for c in world.config.channels:
        row = world.truth_channels.set_index("channel").loc[c.name]
        assert row.true_roi_first_order == pytest.approx(c.target_roi, rel=1e-9)


def test_truth_decomposition_adds_up(world):
    """Expected contributions by source must sum to the expected total that drove outcomes."""
    tc = world.truth_contributions
    exp_total = tc.groupby(["week_start", "geo"]).expected_new_customers.sum()
    realised = world.outcomes.set_index(["week_start", "geo"]).new_customers
    # Realised counts are NegBin around the expected total: check bias, not equality.
    assert realised.sum() / exp_total.sum() == pytest.approx(1.0, abs=0.01)


def test_demand_driven_spend_is_endogenous(world):
    """Brand search spend tracks demand far more closely than its causal effect would imply."""
    nat_spend = world.media[world.media.channel == "search_brand"].groupby("week_start").spend.sum()
    base = (world.truth_contributions.query("source == 'baseline'")
            .groupby("week_start").expected_new_customers.sum())
    assert np.corrcoef(nat_spend, base)[0, 1] > 0.8


def test_business_scale_is_plausible(world):
    annual_rev = world.outcomes.revenue.sum() / (world.config.n_weeks / 52)
    assert 8e6 < annual_rev < 16e6


def test_incremental_outcome_zero_spend_is_zero(world):
    out = incremental_outcome(world, "meta_prospecting", np.zeros(13))
    assert out.new_customers == pytest.approx(0.0, abs=1e-9)


def test_response_has_diminishing_returns_above_reference(world):
    for c in world.config.channels:
        ref = c.annual_spend / 4
        grid = ref * np.array([1.0, 1.5, 2.0, 3.0])
        m = [marginal_roi(world, c.name, s)["mroi_first_order_revenue"] for s in grid]
        assert all(a > b for a, b in zip(m, m[1:], strict=False)), c.name


def test_curve_is_monotone(world):
    curve = quarterly_curve(world, "tiktok", np.linspace(0, 400_000, 9))
    rev = [o.first_order_revenue for o in curve]
    assert all(b >= a for a, b in zip(rev, rev[1:], strict=False))
