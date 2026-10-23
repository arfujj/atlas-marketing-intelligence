"""Every Halden metric must equal an independent SQL computation run directly on the
simulator's raw parquet files (no dbt models, no metric-layer code involved).

This complements test_metrics.py (independent pandas). The SQL here is written from the
metric *definitions* in docs, so a bug in the dbt marts or in the YAML layer shows up as a
mismatch in at least one of the two independent checks.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from atlas.metrics import Filters, query_metric

FILTERS = {
    "all": Filters(),
    "slice": Filters(start=date(2025, 1, 6), end=date(2025, 12, 29), geos=("R02", "R07")),
    "recent": Filters(start=date(2026, 4, 6), geos=("R03",)),
}
CHANNEL_FILTER = Filters(start=date(2026, 1, 5), channels=("search_brand", "tiktok"))


def _where(f: Filters, channel: bool = False) -> str:
    c = ["true"]
    if f.start:
        c.append(f"cast(week_start as date) >= date '{f.start}'")
    if f.end:
        c.append(f"cast(week_start as date) <= date '{f.end}'")
    if f.geos:
        c.append("geo in (" + ", ".join(f"'{g}'" for g in f.geos) + ")")
    if channel and f.channels:
        c.append("channel in (" + ", ".join(f"'{x}'" for x in f.channels) + ")")
    return " and ".join(c)


def independent_sql(d: str, name: str, f: Filters) -> float:
    out, media = f"'{d}/observed/outcomes_weekly.parquet'", f"'{d}/observed/media_weekly.parquet'"
    ses, jr = f"'{d}/observed/sessions_weekly.parquet'", f"'{d}/observed/journeys.parquet'"
    w, wc = _where(f), _where(f, channel=True)
    o = lambda expr: f"(select {expr} from {out} where {w})"  # noqa: E731
    m = lambda expr: f"(select {expr} from {media} where {wc})"  # noqa: E731
    s = lambda expr: f"(select {expr} from {ses} where {w})"  # noqa: E731
    lc = (f"(select channel, first_order_revenue from (select *, "
          f"string_split(path, '>')[-1] as channel from {jr} where converted) where {wc} "
          f"and channel not in ('organic_search', 'direct'))")
    sql = {
        "revenue": o("sum(revenue)"),
        "first_order_revenue": o("sum(first_order_revenue)"),
        "repeat_revenue": o("sum(repeat_revenue)"),
        "first_order_contribution": o("sum(first_order_contribution)"),
        "repeat_contribution": o("sum(repeat_contribution)"),
        "new_customers": o("sum(new_customers)"),
        "orders": o("sum(orders)"),
        "sessions": s("sum(sessions)"),
        "spend": m("sum(spend)"),
        "clicks": m("sum(clicks)"),
        "impressions": m("sum(impressions)"),
        "contribution_profit": f"{o('sum(first_order_contribution) + sum(repeat_contribution)')}"
                               f" - {m('sum(spend)')}",
        "new_customer_revenue_share": f"{o('sum(first_order_revenue)')} / {o('sum(revenue)')}",
        "mer": f"{o('sum(revenue)')} / {m('sum(spend)')}",
        "conversion_rate": f"{o('sum(orders)')} / {s('sum(sessions)')}",
        "aov": f"{o('sum(revenue)')} / {o('sum(orders)')}",
        "blended_cac": f"{m('sum(spend)')} / {o('sum(new_customers)')}",
        "last_click_conversions": f"(select count(*) from {lc})",
        "last_click_revenue": f"(select sum(first_order_revenue) from {lc})",
        "last_click_roas": f"(select sum(first_order_revenue) from {lc}) / {m('sum(spend)')}",
        "paid_cac_attributed": f"{m('sum(spend)')} / (select count(*) from {lc})",
        "cpc": f"{m('sum(spend)')} / {m('sum(clicks)')}",
        "ctr": f"{m('sum(clicks)')} / {m('sum(impressions)')}",
        "first_order_cm_rate": f"{o('sum(first_order_contribution)')} / "
                               f"{o('sum(first_order_revenue)')}",
    }[name]
    return float(duckdb.sql(f"select {sql}").fetchall()[0][0])


GEO_LEVEL = ["revenue", "first_order_revenue", "repeat_revenue", "first_order_contribution",
             "repeat_contribution", "new_customers", "orders", "sessions", "spend",
             "contribution_profit", "new_customer_revenue_share", "mer", "conversion_rate",
             "aov", "blended_cac", "first_order_cm_rate", "last_click_roas",
             "paid_cac_attributed", "cpc", "ctr", "clicks", "impressions"]


@pytest.mark.parametrize("name", GEO_LEVEL)
@pytest.mark.parametrize("fkey", list(FILTERS))
def test_metric_equals_independent_sql(halden_db, halden_dir, name, fkey):
    f = FILTERS[fkey]
    got = query_metric(halden_db, name, f).data["value"].iloc[0]
    assert got == pytest.approx(independent_sql(str(halden_dir), name, f), rel=1e-9)


@pytest.mark.parametrize("name", ["spend", "last_click_conversions", "last_click_revenue",
                                  "last_click_roas", "paid_cac_attributed", "cpc", "ctr"])
def test_channel_metric_equals_independent_sql(halden_db, halden_dir, name):
    got = query_metric(halden_db, name, CHANNEL_FILTER).data["value"].iloc[0]
    assert got == pytest.approx(independent_sql(str(halden_dir), name, CHANNEL_FILTER),
                                rel=1e-9)


def test_52_week_value_equals_independent_sql(halden_db, halden_dir):
    out = f"'{halden_dir}/observed/outcomes_weekly.parquet'"
    expect = duckdb.sql(f"""
        with last as (select * from {out} where cast(week_start as date) >
                      (select max(cast(week_start as date)) from {out}) - interval 52 week)
        select (sum(first_order_revenue) + sum(repeat_revenue)) / sum(new_customers),
               sum(repeat_contribution) / sum(first_order_contribution) from last""").fetchall()[0]
    got = query_metric(halden_db, "est_value_52w_per_new_customer").data.value.iloc[0]
    mult = query_metric(halden_db, "repeat_value_multiplier").data.value.iloc[0]
    assert got == pytest.approx(expect[0], rel=1e-9)
    assert mult == pytest.approx(expect[1], rel=1e-9)
