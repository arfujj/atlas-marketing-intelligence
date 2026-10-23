select
    journey_id,
    cast(week_start as date) as week_start,
    geo,
    cast(converted as boolean) as converted,
    cast(weight as double) as weight,
    path,
    cast(n_touches as integer) as n_touches,
    cast(first_order_revenue as double) as first_order_revenue
from {{ source('halden', 'journeys') }}
