-- OBSERVED. Item lines of deduplicated transactions only (lines of duplicate events and of
-- events without a usable transaction id are excluded; see fct_ga4_transactions).
select
    i.transaction_id,
    i.user_pseudo_id,
    i.event_utc,
    cast(i.event_utc at time zone 'UTC' as date) as event_date,
    i.item_id,
    i.item_name,
    i.item_brand,
    i.item_category,
    i.price_in_usd,
    i.quantity,
    coalesce(i.item_revenue_in_usd, 0) as item_revenue,
    i.item_revenue_in_usd is null as item_revenue_missing
from {{ ref('stg_ga4__purchase_items') }} as i
join {{ ref('fct_ga4_transactions') }} as t
    on t.transaction_id = i.transaction_id and t.event_utc = i.event_utc
