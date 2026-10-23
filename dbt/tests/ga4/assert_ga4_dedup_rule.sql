-- Documented dedup rule: one row per valid transaction_id, the earliest event; duplicates and
-- unidentified events never reach revenue; every revenue rollup agrees with the fact table.
with ranked as (select * from {{ ref('int_ga4__purchase_events_ranked') }}),
earliest as (
    select transaction_id, min(event_utc) as first_utc
    from ranked where transaction_id_status = 'valid' group by 1
),
violations as (
    -- kept event is not the earliest one
    select 'kept_not_earliest' as issue, count(*) as n
    from {{ ref('fct_ga4_transactions') }} as t join earliest as e using (transaction_id)
    where t.event_utc <> e.first_utc
    union all
    -- a valid transaction id is missing from the fact table, or appears twice
    select 'coverage', abs((select count(*) from earliest)
                           - (select count(distinct transaction_id)
                              from {{ ref('fct_ga4_transactions') }}))
    union all
    select 'unidentified_in_fact', count(*) from {{ ref('fct_ga4_transactions') }}
    where transaction_id is null or transaction_id = '(not set)'
    union all
    -- revenue agrees across the fact table, the daily mart and the funnel mart (cents)
    select 'daily_revenue', case when abs((select sum(revenue) from {{ ref('mart_ga4_daily') }})
        - (select sum(revenue) from {{ ref('fct_ga4_transactions') }})) > 0.01 then 1 else 0 end
    union all
    select 'funnel_revenue', case when abs((select sum(revenue) from {{ ref('mart_ga4_funnel') }})
        - (select sum(revenue) from {{ ref('fct_ga4_transactions') }})) > 0.01 then 1 else 0 end
    union all
    -- naive revenue = kept + duplicate + unidentified
    select 'naive_partition', case when abs(
        (select sum(revenue_naive) from {{ ref('mart_ga4_daily') }})
        - (select sum(purchase_revenue_usd) from ranked)) > 0.01 then 1 else 0 end
)
select * from violations where n > 0
