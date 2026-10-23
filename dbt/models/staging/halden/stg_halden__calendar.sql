select
    cast(week_start as date) as week_start,
    cast(promo_week as boolean) as is_promo_week,
    cast(bfcm_week as boolean) as is_bfcm_week,
    cast(gifting_week as boolean) as is_gifting_week
from {{ source('halden', 'calendar_weekly') }}
