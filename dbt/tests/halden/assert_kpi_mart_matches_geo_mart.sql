-- National KPI mart must equal the sum of the geo mart for every additive measure.
with g as (
    select week_start,
           sum(revenue) as revenue, sum(new_customers) as new_customers,
           sum(orders) as orders, sum(sessions) as sessions,
           sum(contribution_profit) as contribution_profit
    from {{ ref('fct_geo_week') }}
    group by 1
)
select k.week_start
from {{ ref('mart_kpi_weekly') }} as k
join g using (week_start)
where abs(k.revenue - g.revenue) > 0.01
   or k.new_customers <> g.new_customers
   or k.orders <> g.orders
   or k.sessions <> g.sessions
   or abs(k.contribution_profit - g.contribution_profit) > 0.01
