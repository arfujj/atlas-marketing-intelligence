-- One row per touch. Positions are 1-based; `is_last` marks the touch that last-click credits.
with split as (
    select
        journey_id, week_start, geo, converted, weight, n_touches, first_order_revenue,
        string_split(path, '>') as touches
    from {{ ref('stg_halden__journeys') }}
)
select
    journey_id, week_start, geo, converted, weight, n_touches, first_order_revenue,
    unnest(touches) as channel,
    generate_subscripts(touches, 1) as touch_position
from split
