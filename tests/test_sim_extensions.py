"""Simulator v0.2: sessions, incidents, journeys and randomised worlds."""

import numpy as np
import pandas as pd
import pytest

from atlas.sim import default_world, simulate
from atlas.sim.config import WORLD_REGIMES, sample_world

SEED = 20261023


@pytest.fixture(scope="module")
def world():
    return simulate(default_world(), seed=SEED)


@pytest.fixture(scope="module")
def clean():
    cfg = default_world().model_copy(update={"incident_mode": "none"})
    return simulate(cfg, seed=SEED, journeys=False)


def _nat(df, col, by="week_start"):
    return df.groupby(by)[col].sum()


def test_scheduled_incidents_recorded(world):
    inc = world.incidents.set_index("kind")
    assert set(inc.index) == {"tracking_outage", "cpc_spike", "checkout_incident"}
    hist = world.weeks[world.burn_in:]
    assert (world.incidents.start_week >= hist[-20]).all()
    assert inc.loc["checkout_incident", "real_business_loss"]
    assert not world.incidents.changes_true_media_effect.any()


def test_tracking_outage_only_changes_recorded_outcomes(world, clean):
    row = world.incidents.set_index("kind").loc["tracking_outage"]
    key = (world.outcomes.geo == row.geo) & (world.outcomes.week_start == row.start_week)
    a = world.outcomes[key].iloc[0]
    b = clean.outcomes[key].iloc[0]
    assert a.revenue == pytest.approx(b.revenue * (1 - row.magnitude), rel=1e-9)
    # sessions and clicks are unaffected
    ms = world.media[(world.media.geo == row.geo) & (world.media.week_start == row.start_week)]
    mc = clean.media[(clean.media.geo == row.geo) & (clean.media.week_start == row.start_week)]
    np.testing.assert_allclose(ms.clicks.to_numpy(), mc.clicks.to_numpy())
    other = ~key
    np.testing.assert_allclose(world.outcomes[other & (world.outcomes.week_start
                                                       < row.start_week)].revenue,
                               clean.outcomes[other & (clean.outcomes.week_start
                                                       < row.start_week)].revenue)


def test_cpc_spike_inflates_billed_spend_not_clicks(world, clean):
    row = world.incidents.set_index("kind").loc["cpc_spike"]
    m, c = world.media, clean.media
    sel = (m.channel == row.channel) & m.week_start.between(row.start_week, row.end_week)
    assert m[sel].spend.sum() == pytest.approx(c[sel].spend.sum() * (1 + row.magnitude))
    np.testing.assert_allclose(m[sel].clicks, c[sel].clicks)
    # the true effect is driven by effective spend, so truth is identical
    pd.testing.assert_frame_equal(world.truth_contributions, clean.truth_contributions)


def test_checkout_incident_is_real_and_sitewide(world, clean):
    row = world.incidents.set_index("kind").loc["checkout_incident"]
    wk = row.start_week
    o, oc = world.outcomes, clean.outcomes
    ratio = o[o.week_start == wk].new_customers.sum() / oc[oc.week_start == wk].new_customers.sum()
    assert ratio == pytest.approx(1 - row.magnitude, abs=0.03)
    ratio_rev = o[o.week_start == wk].revenue.sum() / oc[oc.week_start == wk].revenue.sum()
    assert ratio_rev == pytest.approx(1 - row.magnitude, abs=0.03)
    s, sc = world.sessions, clean.sessions
    assert s[s.week_start == wk].sessions.sum() == pytest.approx(
        sc[sc.week_start == wk].sessions.sum(), rel=0.02)


def test_sessions_define_conversion_rate(world):
    s = world.sessions
    assert not s.duplicated(["week_start", "geo"]).any()
    assert (s.sessions == s.organic_direct_sessions + s.paid_sessions).all()
    paid = world.media.groupby(["geo", "week_start"]).clicks.sum()
    merged = s.set_index(["geo", "week_start"]).paid_sessions
    np.testing.assert_allclose(merged.sort_index(), paid.sort_index())
    cr = world.outcomes.orders.sum() / s.sessions.sum()
    assert 0.015 < cr < 0.06


def test_journeys_cover_every_recorded_new_customer(world):
    j = world.journeys
    conv = j[j.converted]
    assert len(conv) == int(world.outcomes.new_customers.sum())
    assert j.journey_id.is_unique
    assert (j.n_touches >= 1).all()
    assert len(world.journey_sources) == len(conv)


def test_paid_causal_source_appears_in_path(world):
    j = world.journeys[world.journeys.converted].merge(world.journey_sources, on="journey_id")
    paid = j[j.causal_source != "baseline"]
    hit = [s in p.split(">") for s, p in zip(paid.causal_source, paid.path, strict=True)]
    assert all(hit)


def test_harvest_channels_overrepresented_last(world):
    j = world.journeys[world.journeys.converted].merge(world.journey_sources, on="journey_id")
    last = j.path.str.split(">").str[-1]
    for h in ("search_brand", "meta_retargeting"):
        assert (last == h).mean() > 5 * (j.causal_source == h).mean()


def test_journeys_deterministic():
    a = simulate(default_world(), seed=3)
    b = simulate(default_world(), seed=3)
    pd.testing.assert_frame_equal(a.journeys, b.journeys)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_sample_world_valid_and_deterministic(seed):
    cfg1, meta1 = sample_world(seed)
    cfg2, _ = sample_world(seed)
    assert cfg1.fingerprint() == cfg2.fingerprint()
    assert meta1["regime"] in WORLD_REGIMES
    w = simulate(cfg1, seed=seed, journeys=False)
    tc = w.truth_channels.set_index("channel")
    for c in cfg1.channels:
        assert tc.loc[c.name, "true_roi_first_order"] == pytest.approx(c.target_roi, rel=1e-9)
    assert len(w.incidents) > 0
    assert not w.outcomes.isna().any().any()


def test_collinear_regime_has_correlated_planned_spend():
    cfg, _ = sample_world(11, regime="collinear")
    w = simulate(cfg, seed=11, journeys=False)
    nat = w.media.pivot_table(index="week_start", columns="channel", values="spend",
                              aggfunc="sum")
    planned = [c.name for c in cfg.channels
               if c.spend_policy == "planned" and c.flighting == "always_on"
               and c.launch_week == 0]
    corr = np.corrcoef(nat[planned].to_numpy().T)
    off = corr[~np.eye(len(planned), dtype=bool)]
    assert off.min() > 0.8
