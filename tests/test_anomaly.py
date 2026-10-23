import numpy as np
import pandas as pd
import pytest

from atlas.anomaly import (
    alerts,
    explain_week,
    ga4_late_january,
    match_incidents,
    robust_z,
    score_halden,
    weekly_features,
)
from atlas.sim import default_world, simulate

THRESHOLDS = {"national": 3.0, "region": 3.5, "channel": 3.5}


def _weekly(n: int = 120, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    weeks = pd.date_range("2024-01-01", periods=n, freq="W-MON")
    season = 1 + 0.2 * np.sin(2 * np.pi * weeks.day_of_year / 365.25)
    return pd.Series(1000 * season * np.exp(rng.normal(0, 0.03, n)), index=weeks)


def test_robust_z_flags_a_drop_and_ignores_normal_weeks():
    s = _weekly()
    s.iloc[-1] *= 0.7
    z = robust_z(s, weekly_features(pd.DatetimeIndex(s.index), None), start=100, min_train=78)
    assert z.z.iloc[-1] < -5
    assert (z.z.iloc[:-1].abs() < 4).all()


def test_past_outlier_does_not_mask_a_new_one():
    s = _weekly(seed=1)
    s.iloc[90] *= 3.0  # a large past spike stays in the training window
    s.iloc[-1] *= 0.7
    z = robust_z(s, weekly_features(pd.DatetimeIndex(s.index), None), start=100, min_train=78)
    assert z.z.iloc[-1] < -5


@pytest.fixture(scope="module")
def flagship():
    w = simulate(default_world(), seed=20261023, journeys=False)
    return w, score_halden(w.media, w.outcomes, w.sessions, w.calendar)


def test_flagship_incidents_are_all_detected(flagship):
    w, sc = flagship
    _, st = match_incidents(alerts(sc, THRESHOLDS), w.incidents)
    assert st["recall"] == 1.0


def test_explanations_match_the_injected_cause(flagship):
    w, sc = flagship
    inc = w.incidents.set_index("kind")

    def top(kind):
        wk = inc.loc[kind, "start_week"]
        return explain_week(sc, w.media, w.outcomes, w.sessions, wk, THRESHOLDS)["hypotheses"]

    tracking = top("tracking_outage")
    geo = inc.loc["tracking_outage", "geo"]
    assert tracking[0]["title"].startswith(f"Measurement failure in {geo}")
    cpc = top("cpc_spike")
    assert cpc[0]["status"] == "Confirmed" and cpc[0]["title"].startswith("search_nonbrand")
    checkout = top("checkout_incident")
    assert checkout[0]["title"].startswith("Site-wide")
    # A site-wide drop must not also be blamed on regional tracking.
    assert not any(h["title"].startswith("Measurement failure") for h in checkout)


def test_ga4_late_january_separates_instrumentation_from_demand():
    days = pd.date_range("2021-01-01", "2021-01-31")
    after = days >= "2021-01-26"
    n = len(days)
    daily = pd.DataFrame({
        "date": days, "sessions": np.full(n, 3000), "ev_add_to_cart": np.full(n, 400),
        "ev_begin_checkout": np.full(n, 200), "purchase_events": np.full(n, 40),
        "purchase_sessions": np.full(n, 38),
        "unidentified_purchase_events": np.where(after, 35, 2),
        "transactions": np.where(after, 5, 38),
        "revenue_naive": np.where(after, 200.0, 2400.0),
        "revenue": np.where(after, 180.0, 2300.0),
    })
    r = ga4_late_january(daily, pd.DataFrame({"period": [], "series": [], "z": []}))
    assert r["conclusion"].startswith("Instrumentation, not demand")
    assert r["evidence_status"] == "Supported hypothesis"
