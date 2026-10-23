select
    cast(event_date as date) as event_date,
    event_name,
    case when item_category is null or trim(item_category) = '' then '(blank)'
         else item_category end as item_category,
    item_events,
    users
from {{ source('ga4', 'item_funnel_daily') }}
