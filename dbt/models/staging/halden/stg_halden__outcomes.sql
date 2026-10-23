select
    cast(week_start as date) as week_start,
    geo,
    cast(new_customers as bigint) as new_customers,
    cast(orders as bigint) as orders,
    cast(orders as bigint) - cast(new_customers as bigint) as repeat_orders,
    cast(revenue as double) as revenue,
    cast(first_order_revenue as double) as first_order_revenue,
    cast(first_order_contribution as double) as first_order_contribution,
    cast(repeat_revenue as double) as repeat_revenue,
    cast(repeat_contribution as double) as repeat_contribution
from {{ source('halden', 'outcomes_weekly') }}
