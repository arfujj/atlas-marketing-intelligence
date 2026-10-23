select
    transaction_id,
    user_pseudo_id,
    cast(event_utc as timestamptz) as event_utc,
    item_id,
    item_name,
    item_brand,
    case when item_category is null or trim(item_category) = '' then '(blank)'
         else item_category end as item_category,
    price_in_usd,
    quantity,
    item_revenue_in_usd
from {{ source('ga4', 'purchase_items') }}
