"""Every metric in the YAML layer must equal an independent pandas computation made directly
from the simulator's output tables (not from the dbt marts)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from atlas.metrics import (
    Filters,
    MetricNotApplicable,
    load_metrics,
    metric_catalog,
    query_metric,
)

F_ALL = Filters()
F_SLICE = Filters(start=date(2025, 1, 6), end=date(2025, 12, 29), geos=("R02", "R07"))
F_CHAN = Filters(start=date(2026, 1, 5), channels=("search_brand", "tiktok"))


def _geo_frame(w) -> pd.DataFrame:
    o = w.outcomes.copy()
    o = o.merge(w.sessions, on=["week_start", "geo"])
    sp = w.media.groupby(["week_start", "geo"], as_index=False)[["spend", "clicks"]].sum()
    o = o.merge(sp, on=["week_start", "geo"])
    o["week_start"] = pd.to_datetime(o.week_start).dt.date
    return o


def _channel_frame(w) -> pd.DataFrame:
    m = w.media.copy()
    j = w.journeys[w.journeys.converted].copy()
    j["channel"] = j.path.str.split(">").str[-1]
    lc = j.groupby(["week_start", "geo", "channel"], as_index=False).agg(
        last_click_conversions=("journey_id", "size"),
        last_click_revenue=("first_order_revenue", "sum"))
    m = m.merge(lc, on=["week_start", "geo", "channel"], how="left").fillna(
        {"last_click_conversions": 0, "last_click_revenue": 0})
    m["week_start"] = pd.to_datetime(m.week_start).dt.date
    return m


def _filt(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    keep = np.ones(len(df), bool)
    if f.start:
        keep &= df.week_start >= f.start
    if f.end:
        keep &= df.week_start <= f.end
    if f.geos:
        keep &= df.geo.isin(f.geos)
    if f.channels and "channel" in df:
        keep &= df.channel.isin(f.channels)
    return df[keep]


GEO_SUMS = {
    "revenue": "revenue", "first_order_revenue": "first_order_revenue",
    "repeat_revenue": "repeat_revenue", "first_order_contribution": "first_order_contribution",
    "repeat_contribution": "repeat_contribution", "new_customers": "new_customers",
    "orders": "orders", "sessions": "sessions",
}
CHAN_SUMS = {"spend": "spend", "last_click_conversions": "last_click_conversions",
             "last_click_revenue": "last_click_revenue", "clicks": "clicks",
             "impressions": "impressions"}


def independent(w, name: str, f: Filters) -> float:
    g, c = _filt(_geo_frame(w), f), _filt(_channel_frame(w), f)
    s = lambda col: float(g[col].sum())  # noqa: E731
    sc = lambda col: float(c[col].sum())  # noqa: E731
    if name in GEO_SUMS:
        return s(GEO_SUMS[name])
    if name in CHAN_SUMS:
        return sc(CHAN_SUMS[name])
    return {
        "contribution_profit": s("first_order_contribution") + s("repeat_contribution")
        - s("spend"),
        "new_customer_revenue_share": s("first_order_revenue") / s("revenue"),
        "mer": s("revenue") / s("spend"),
        "conversion_rate": s("orders") / s("sessions"),
        "aov": s("revenue") / s("orders"),
        "blended_cac": s("spend") / s("new_customers"),
        "last_click_roas": sc("last_click_revenue") / sc("spend"),
        "paid_cac_attributed": sc("spend") / sc("last_click_conversions"),
        "cpc": sc("spend") / sc("clicks"),
        "ctr": sc("clicks") / sc("impressions"),
        "first_order_cm_rate": s("first_order_contribution") / s("first_order_revenue"),
    }[name]


SIMPLE_AND_RATIO = [m for m, d in load_metrics().items() if d.type != "trailing"]


@pytest.mark.parametrize("name", SIMPLE_AND_RATIO)
@pytest.mark.parametrize("filters", [F_ALL, F_SLICE], ids=["all", "slice"])
def test_metric_matches_independent_computation(halden_db, halden_world, name, filters):
    got = query_metric(halden_db, name, filters).data["value"].iloc[0]
    assert got == pytest.approx(independent(halden_world, name, filters), rel=1e-9)


CHANNEL_METRICS = [m for m in SIMPLE_AND_RATIO if "channel" in
                   {d for d in load_metrics()[m].dimensions}
                   or (load_metrics()[m].type == "ratio" and all(
                       "channel" in load_metrics()[x].dimensions
                       for x in (load_metrics()[m].numerator, load_metrics()[m].denominator)))]


@pytest.mark.parametrize("name", CHANNEL_METRICS)
def test_channel_filtered_metrics(halden_db, halden_world, name):
    got = query_metric(halden_db, name, F_CHAN).data["value"].iloc[0]
    assert got == pytest.approx(independent(halden_world, name, F_CHAN), rel=1e-9)


def test_grouped_by_channel_sums_to_total(halden_db):
    by = query_metric(halden_db, "spend", F_SLICE, group_by=("channel",)).data
    tot = query_metric(halden_db, "spend", F_SLICE).data.value.iloc[0]
    assert by.value.sum() == pytest.approx(tot, rel=1e-12)
    assert len(by) == 6


def test_ratio_by_week_is_ratio_of_sums(halden_db, halden_world):
    by = query_metric(halden_db, "conversion_rate", F_SLICE, group_by=("week_start",)).data
    g = _filt(_geo_frame(halden_world), F_SLICE).groupby("week_start")[["orders", "sessions"]].sum()
    np.testing.assert_allclose(by.value.to_numpy(), (g.orders / g.sessions).to_numpy())


@pytest.mark.parametrize("name", ["mer", "revenue", "conversion_rate", "blended_cac"])
def test_channel_filter_rejected_where_undefined(halden_db, name):
    with pytest.raises(MetricNotApplicable):
        query_metric(halden_db, name, F_CHAN)


def test_trailing_value_estimate(halden_db, halden_world):
    g = _geo_frame(halden_world)
    end = g.week_start.max()
    last = g[g.week_start > end - pd.Timedelta(weeks=52)]
    expect = (last.first_order_revenue.sum() + last.repeat_revenue.sum()) / last.new_customers.sum()
    got = query_metric(halden_db, "est_value_52w_per_new_customer").data.value.iloc[0]
    assert got == pytest.approx(expect, rel=1e-9)
    mult = query_metric(halden_db, "repeat_value_multiplier").data.value.iloc[0]
    assert mult == pytest.approx(last.repeat_contribution.sum()
                                 / last.first_order_contribution.sum(), rel=1e-9)


def test_catalog_has_evidence_labels():
    cat = metric_catalog()
    assert {c["evidence_type"] for c in cat} <= {
        "Observed", "Attributed", "Modeled", "Experimental", "Simulated", "Assumption"}
    assert next(c for c in cat if c["name"] == "last_click_roas")["evidence_type"] == "Attributed"
