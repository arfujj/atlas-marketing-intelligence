-- Every recorded new customer has exactly one converting journey, so last-click conversions
-- (paid + organic/direct) must equal recorded new customers in every geo-week, and the
-- credited revenue must equal recorded first-order revenue.
with credit as (
    select week_start, geo,
           sum(last_click_conversions) as conversions,
           sum(last_click_revenue) as revenue
    from {{ ref('int_halden__last_click') }}
    group by 1, 2
)
select o.week_start, o.geo, o.new_customers, c.conversions, o.first_order_revenue, c.revenue
from {{ ref('stg_halden__outcomes') }} as o
left join credit as c using (week_start, geo)
where coalesce(c.conversions, 0) <> o.new_customers
   or (o.new_customers > 0 and abs(coalesce(c.revenue, 0) - o.first_order_revenue) > 0.01)
