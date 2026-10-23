-- OBSERVED. One row per day: session funnel (by session start date), purchase events
-- (by event date), deduplicated transactions and revenue, and raw event counts used to
-- separate demand changes from instrumentation changes.
with s as (
    select
        session_date as date,
        count(*) as sessions,
        count(distinct user_pseudo_id) as users,
        count(*) filter (where is_engaged) as engaged_sessions,
        count(*) filter (where has_view_item) as view_item_sessions,
        count(*) filter (where has_add_to_cart) as add_to_cart_sessions,
        count(*) filter (where has_begin_checkout) as begin_checkout_sessions,
        count(*) filter (where has_add_payment_info) as add_payment_info_sessions,
        count(*) filter (where has_purchase) as purchase_sessions,
        count(*) filter (where crosses_midnight) as midnight_crossing_sessions
    from {{ ref('stg_ga4__sessions') }}
    group by 1
),
p as (
    select
        event_date as date,
        count(*) as purchase_events,
        count(*) filter (where dedup_status = 'kept') as transactions,
        count(*) filter (where dedup_status = 'duplicate') as duplicate_purchase_events,
        count(*) filter (where dedup_status = 'unidentified') as unidentified_purchase_events,
        sum(purchase_revenue_usd) as revenue_naive,
        coalesce(sum(purchase_revenue_usd) filter (where dedup_status = 'kept'), 0) as revenue,
        coalesce(sum(purchase_revenue_usd) filter (where dedup_status = 'unidentified'), 0)
            as revenue_unidentified
    from {{ ref('int_ga4__purchase_events_ranked') }}
    group by 1
),
e as (
    select
        event_date as date,
        sum(events) filter (where event_name = 'session_start') as ev_session_start,
        sum(events) filter (where event_name = 'view_item') as ev_view_item,
        sum(events) filter (where event_name = 'add_to_cart') as ev_add_to_cart,
        sum(events) filter (where event_name = 'begin_checkout') as ev_begin_checkout,
        sum(events) filter (where event_name = 'add_payment_info') as ev_add_payment_info,
        sum(events) filter (where event_name = 'purchase') as ev_purchase
    from {{ ref('stg_ga4__events_daily') }}
    group by 1
)
select
    s.*,
    coalesce(p.purchase_events, 0) as purchase_events,
    coalesce(p.transactions, 0) as transactions,
    coalesce(p.duplicate_purchase_events, 0) as duplicate_purchase_events,
    coalesce(p.unidentified_purchase_events, 0) as unidentified_purchase_events,
    coalesce(p.revenue_naive, 0) as revenue_naive,
    coalesce(p.revenue, 0) as revenue,
    coalesce(p.revenue_unidentified, 0) as revenue_unidentified,
    coalesce(e.ev_session_start, 0) as ev_session_start,
    coalesce(e.ev_view_item, 0) as ev_view_item,
    coalesce(e.ev_add_to_cart, 0) as ev_add_to_cart,
    coalesce(e.ev_begin_checkout, 0) as ev_begin_checkout,
    coalesce(e.ev_add_payment_info, 0) as ev_add_payment_info,
    coalesce(e.ev_purchase, 0) as ev_purchase,
    s.purchase_sessions / s.sessions as session_conversion_rate,
    coalesce(p.revenue, 0) / nullif(p.transactions, 0) as aov,
    coalesce(p.unidentified_purchase_events, 0) / nullif(p.purchase_events, 0)
        as unidentified_share
from s
left join p using (date)
left join e using (date)
