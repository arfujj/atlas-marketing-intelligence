-- ATTRIBUTED (not causal): last-touch credit for each converting journey, by geo-week-channel.
-- Organic/direct last touches are kept so totals reconcile to recorded new customers.
{{ config(materialized='table') }}
select
    week_start,
    geo,
    channel,
    count(*) as last_click_conversions,
    sum(first_order_revenue) as last_click_revenue
from {{ ref('int_halden__journey_touches') }}
where converted and touch_position = n_touches
group by 1, 2, 3
