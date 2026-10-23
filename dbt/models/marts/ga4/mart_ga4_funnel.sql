-- OBSERVED. Session funnel by day × device × FIRST-USER channel group × country group.
-- Steps are "sessions that reached the step" (a session can skip steps in GA4, so a later step
-- can occasionally exceed an earlier one). Revenue = deduplicated transactions in the session.
-- first_user_channel_group is the user's acquisition channel, not the session's source.
with top_countries as (
    select country from {{ ref('stg_ga4__sessions') }}
    group by 1 order by count(*) desc limit 10
),
tx as (
    select session_key, count(*) as transactions, sum(revenue) as revenue
    from {{ ref('fct_ga4_transactions') }}
    group by 1
)
select
    s.session_date as date,
    s.device_category,
    s.first_user_channel_group,
    case when s.country in (select country from top_countries) then s.country
         else 'Rest of world' end as country_group,
    count(*) as sessions,
    count(*) filter (where s.is_engaged) as engaged_sessions,
    count(*) filter (where s.has_view_item) as view_item_sessions,
    count(*) filter (where s.has_add_to_cart) as add_to_cart_sessions,
    count(*) filter (where s.has_begin_checkout) as begin_checkout_sessions,
    count(*) filter (where s.has_add_shipping_info) as add_shipping_info_sessions,
    count(*) filter (where s.has_add_payment_info) as add_payment_info_sessions,
    count(*) filter (where s.has_purchase) as purchase_sessions,
    coalesce(sum(tx.transactions), 0) as transactions,
    coalesce(sum(tx.revenue), 0) as revenue
from {{ ref('stg_ga4__sessions') }} as s
left join tx using (session_key)
group by 1, 2, 3, 4
