-- OBSERVED. Item-category funnel by day: item events (view_item, add_to_cart, begin_checkout,
-- purchase) from the raw event export, plus deduplicated item revenue and quantity.
with ev as (
    select
        event_date as date,
        item_category,
        sum(item_events) filter (where event_name = 'view_item') as item_views,
        sum(item_events) filter (where event_name = 'add_to_cart') as item_add_to_carts,
        sum(item_events) filter (where event_name = 'begin_checkout') as item_checkouts,
        sum(item_events) filter (where event_name = 'purchase') as item_purchase_events
    from {{ ref('stg_ga4__item_funnel_daily') }}
    group by 1, 2
),
rev as (
    select event_date as date, item_category,
           sum(item_revenue) as item_revenue, sum(quantity) as item_quantity,
           count(distinct transaction_id) as transactions
    from {{ ref('fct_ga4_item_lines') }}
    group by 1, 2
)
select
    coalesce(ev.date, rev.date) as date,
    coalesce(ev.item_category, rev.item_category) as item_category,
    coalesce(ev.item_views, 0) as item_views,
    coalesce(ev.item_add_to_carts, 0) as item_add_to_carts,
    coalesce(ev.item_checkouts, 0) as item_checkouts,
    coalesce(ev.item_purchase_events, 0) as item_purchase_events,
    coalesce(rev.item_revenue, 0) as item_revenue,
    coalesce(rev.item_quantity, 0) as item_quantity,
    coalesce(rev.transactions, 0) as transactions
from ev
full outer join rev on ev.date = rev.date and ev.item_category = rev.item_category
