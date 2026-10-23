-- Event-level revenue (purchase_revenue_in_usd) and item-level revenue (sum of
-- item_revenue_in_usd) must reconcile: in total within 0.1% (raw and deduplicated), and
-- exactly for at least 80% of deduplicated transactions (observed: 3,618 of 4,451).
with raw as (
    select
        (select sum(purchase_revenue_usd) from {{ ref('stg_ga4__purchase_events') }}) as ev,
        (select sum(item_revenue_in_usd) from {{ ref('stg_ga4__purchase_items') }}) as it
),
dedup as (
    select sum(revenue) as ev, sum(item_revenue) as it,
           avg(item_revenue_matches::int) as match_share
    from {{ ref('fct_ga4_transactions') }}
)
select 'raw' as level, ev, it, null as match_share from raw where abs(ev - it) / ev > 0.001
union all
select 'dedup', ev, it, match_share from dedup
where abs(ev - it) / ev > 0.001 or match_share < 0.80
