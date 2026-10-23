-- Raw purchase events, one row each (duplicates kept on purpose). transaction_id_status
-- separates ids that can be deduplicated ('valid') from '(not set)' and NULL ids.
select
    row_number() over (
        order by event_utc, user_pseudo_id, transaction_id, purchase_revenue_usd
    ) as purchase_event_id,
    user_pseudo_id,
    ga_session_id,
    user_pseudo_id || '-' || cast(ga_session_id as varchar) as session_key,
    cast(event_date as date) as event_date,
    cast(event_utc as timestamptz) as event_utc,
    transaction_id,
    case
        when transaction_id is null then 'null'
        when transaction_id = '(not set)' then 'not_set'
        else 'valid'
    end as transaction_id_status,
    purchase_revenue_usd,
    total_item_quantity,
    unique_items,
    device_category,
    coalesce(country, '(not set)') as country,
    first_user_source,
    first_user_medium
from {{ source('ga4', 'purchase_events') }}
