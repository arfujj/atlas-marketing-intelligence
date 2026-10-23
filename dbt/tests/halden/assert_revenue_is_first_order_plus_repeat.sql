-- revenue = first-order revenue + repeat revenue, row by row and nationally.
select week_start, geo, revenue, first_order_revenue, repeat_revenue
from {{ ref('fct_geo_week') }}
where abs(revenue - (first_order_revenue + repeat_revenue)) > 0.01
union all
select week_start, 'ALL', revenue, first_order_revenue, repeat_revenue
from {{ ref('mart_kpi_weekly') }}
where abs(revenue - (first_order_revenue + repeat_revenue)) > 0.01
