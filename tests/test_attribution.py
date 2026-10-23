from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.attribution import METHODS, _position_weights, attribute, attribution_table, markov


def _j(rows):
    return pd.DataFrame(rows, columns=["path", "converted", "weight", "first_order_revenue"])


TOY = _j([
    ("a>b", True, 1.0, 100.0),
    ("a", True, 1.0, 50.0),
    ("b", False, 2.0, 0.0),
    ("a>c>b", True, 1.0, 30.0),
])


@pytest.mark.parametrize("n", [1, 2, 3, 7])
@pytest.mark.parametrize("scheme", ["last_click", "first_click", "linear", "position_based"])
def test_position_weights_sum_to_one(n, scheme):
    assert _position_weights(n, scheme).sum() == pytest.approx(1.0)


def test_position_based_40_20_40():
    np.testing.assert_allclose(_position_weights(4, "position_based"), [0.4, 0.1, 0.1, 0.4])


@pytest.mark.parametrize("method", METHODS)
def test_every_method_conserves_conversions_and_revenue(method):
    out = attribute(TOY, method)
    assert out.conversions.sum() == pytest.approx(3.0)
    assert out.revenue.sum() == pytest.approx(180.0)


def test_last_click_toy():
    out = attribute(TOY, "last_click").set_index("channel")
    assert out.loc["b", "revenue"] == pytest.approx(130.0)
    assert out.loc["a", "revenue"] == pytest.approx(50.0)


def test_markov_hand_computed():
    # start->a (3 of 5), start->b (2 of 5). a->b 1/3, a->conv 1/3, a->c 1/3. c->b. b->conv 2/4,
    # b->null 2/4 (weights). P(conv) = 3/5*(1/3 + 1/3*1/2 + 1/3*1/2) + 2/5*1/2 = 0.6
    out = markov(TOY).set_index("channel")
    # removing a: only start->b paths remain converting: 2/5*1/2 = 0.2 -> effect 2/3
    assert out.loc["a", "removal_effect"] == pytest.approx(2 / 3)
    # removing b: 3/5*1/3 = 0.2 -> effect 2/3
    assert out.loc["b", "removal_effect"] == pytest.approx(2 / 3)
    # removing c: 3/5*(1/3 + 1/3*1/2) + 0.2 = 0.5 -> effect 1/6
    assert out.loc["c", "removal_effect"] == pytest.approx(1 / 6)


def test_halden_last_click_overcredits_brand_search(halden_world):
    """The pre-registered trap: last click credits brand search far above its true ROI."""
    t = attribution_table(halden_world.journeys, halden_world.media)
    lc = t[t.method == "last_click"].set_index("channel").roas
    truth = halden_world.truth_channels.set_index("channel").true_roi_first_order_billed
    assert lc["search_brand"] > 10 * truth["search_brand"]
    assert lc["tiktok"] < truth["tiktok"]
    assert set(t.evidence_type) == {"Attributed"}
