-- One row per GA4 session (OBSERVED).
-- Session key = user_pseudo_id + ga_session_id (ga_session_id alone is not unique).
-- session_date = date of the session's first event. In this export event_date equals the
-- UTC calendar date of event_timestamp (verified by assert_ga4_event_date_is_utc_date), so a
-- session that crosses UTC midnight is dated by its start and counted exactly once.
-- first_user_* fields are FIRST-USER acquisition, not the session's own traffic source.
select
    user_pseudo_id || '-' || cast(ga_session_id as varchar) as session_key,
    user_pseudo_id,
    ga_session_id,
    cast(session_start_utc as timestamptz) as session_start_utc,
    cast(session_date as date) as session_date,
    date_trunc('month', cast(session_date as date)) as session_month,
    n_event_dates,
    n_event_dates > 1 as crosses_midnight,
    device_category,
    operating_system,
    coalesce(country, '(not set)') as country,
    first_user_source,
    first_user_medium,
    first_user_campaign,
    case first_user_medium
        when 'organic' then 'Organic Search'
        when '(none)' then 'Direct'
        when 'referral' then 'Referral'
        when 'cpc' then 'Paid Search'
        when '(data deleted)' then 'Data deleted'
        else 'Other (obfuscated)'
    end as first_user_channel_group,
    n_events,
    page_views,
    engaged = 1 as is_engaged,
    engagement_time_msec,
    has_view_item = 1 as has_view_item,
    has_add_to_cart = 1 as has_add_to_cart,
    has_begin_checkout = 1 as has_begin_checkout,
    has_add_shipping_info = 1 as has_add_shipping_info,
    has_add_payment_info = 1 as has_add_payment_info,
    has_purchase = 1 as has_purchase,
    transactions as distinct_transaction_ids,
    purchase_revenue_usd as purchase_revenue_naive
from {{ source('ga4', 'sessions') }}
