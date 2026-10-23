-- Grain: week × region. Recorded business outcomes, site sessions and total paid spend.
with spend as (
    select week_start, geo, sum(spend) as spend, sum(clicks) as paid_clicks
    from {{ ref('stg_halden__media') }}
    group by 1, 2
),
organic_last as (
    select week_start, geo, sum(last_click_conversions) as organic_last_click_conversions
    from {{ ref('int_halden__last_click') }}
    where channel in ('organic_search', 'direct')
    group by 1, 2
)
select
    o.week_start,
    o.geo,
    o.new_customers,
    o.orders,
    o.repeat_orders,
    o.revenue,
    o.first_order_revenue,
    o.repeat_revenue,
    o.first_order_contribution,
    o.repeat_contribution,
    s.sessions,
    s.organic_direct_sessions,
    s.paid_sessions,
    sp.spend,
    sp.paid_clicks,
    coalesce(ol.organic_last_click_conversions, 0) as organic_last_click_conversions,
    o.first_order_contribution + o.repeat_contribution - sp.spend as contribution_profit
from {{ ref('stg_halden__outcomes') }} as o
join {{ ref('stg_halden__sessions') }} as s using (week_start, geo)
join spend as sp using (week_start, geo)
left join organic_last as ol using (week_start, geo)
