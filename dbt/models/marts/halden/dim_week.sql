select
    week_start,
    row_number() over (order by week_start) - 1 as week_index,
    extract(year from week_start) as year,
    extract(quarter from week_start) as quarter,
    extract(year from week_start) || '-Q' || extract(quarter from week_start) as year_quarter,
    is_promo_week,
    is_bfcm_week,
    is_gifting_week
from {{ ref('stg_halden__calendar') }}
