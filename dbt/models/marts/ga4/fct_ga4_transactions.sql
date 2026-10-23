-- OBSERVED. One row per deduplicated transaction (valid transaction_id, earliest event).
-- item_revenue = sum of item lines of the kept event (event-vs-item reconciliation).
with kept as (
    select * from {{ ref('int_ga4__purchase_events_ranked') }} where dedup_status = 'kept'
),
dups as (
    select transaction_id, count(*) - 1 as n_duplicate_events
    from {{ ref('int_ga4__purchase_events_ranked') }}
    where transaction_id_status = 'valid'
    group by 1
),
items as (
    select transaction_id, event_utc,
           sum(item_revenue_in_usd) as item_revenue,
           sum(quantity) as item_quantity,
           count(*) as item_lines
    from {{ ref('stg_ga4__purchase_items') }}
    group by 1, 2
)
select
    k.transaction_id,
    k.user_pseudo_id,
    k.session_key,
    k.event_utc,
    k.event_date,
    date_trunc('month', k.event_date) as event_month,
    k.purchase_revenue_usd as revenue,
    i.item_revenue,
    i.item_quantity,
    i.item_lines,
    abs(k.purchase_revenue_usd - coalesce(i.item_revenue, 0)) < 0.005 as item_revenue_matches,
    d.n_duplicate_events,
    k.device_category,
    k.country,
    k.first_user_source,
    k.first_user_medium,
    row_number() over (partition by k.user_pseudo_id order by k.event_utc) as user_purchase_number
from kept as k
join dups as d using (transaction_id)
left join items as i on i.transaction_id = k.transaction_id and i.event_utc = k.event_utc
