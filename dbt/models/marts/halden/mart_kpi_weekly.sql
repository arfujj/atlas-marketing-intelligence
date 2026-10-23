-- National weekly KPIs (ratios are ratios of sums, never averages of ratios).
select
    g.week_start,
    w.week_index,
    w.year_quarter,
    w.is_promo_week,
    w.is_bfcm_week,
    w.is_gifting_week,
    sum(g.revenue) as revenue,
    sum(g.first_order_revenue) as first_order_revenue,
    sum(g.repeat_revenue) as repeat_revenue,
    sum(g.spend) as spend,
    sum(g.first_order_contribution) as first_order_contribution,
    sum(g.repeat_contribution) as repeat_contribution,
    sum(g.contribution_profit) as contribution_profit,
    sum(g.new_customers) as new_customers,
    sum(g.orders) as orders,
    sum(g.sessions) as sessions,
    sum(g.revenue) / nullif(sum(g.spend), 0) as mer,
    sum(g.spend) / nullif(sum(g.new_customers), 0) as blended_cac,
    sum(g.orders) / nullif(sum(g.sessions), 0) as conversion_rate,
    sum(g.revenue) / nullif(sum(g.orders), 0) as aov
from {{ ref('fct_geo_week') }} as g
join {{ ref('dim_week') }} as w using (week_start)
group by 1, 2, 3, 4, 5, 6
