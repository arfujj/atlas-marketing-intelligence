-- OBSERVED inputs, rule-based segmentation. One row per purchasing user (deduplicated
-- transactions only). Reference date = 2021-02-01, the day after the export ends.
-- R and M are quintile scores (5 = best). F is the raw count bucket (1, 2, 3+) because
-- 88% of buyers (3,263 of 3,702) purchase once in 92 days, so frequency quintiles would be meaningless.
-- The window is 92 days: this is short-run purchase behaviour, not lifetime value.
with u as (
    select
        user_pseudo_id,
        max(event_date) as last_purchase_date,
        min(event_date) as first_purchase_date,
        count(*) as frequency,
        sum(revenue) as monetary
    from {{ ref('fct_ga4_transactions') }}
    group by 1
),
scored as (
    select
        *,
        cast(datediff('day', last_purchase_date, date '2021-02-01') as integer) as recency_days,
        ntile(5) over (order by last_purchase_date) as r_score,
        least(frequency, 3) as f_bucket,
        ntile(5) over (order by monetary) as m_score
    from u
)
select
    *,
    case
        when f_bucket = 3 or (f_bucket = 2 and r_score >= 4) then 'Champions'
        when f_bucket = 2 then 'Repeat buyers'
        when r_score >= 4 and m_score >= 4 then 'Recent high-value'
        when r_score >= 4 then 'Recent one-time'
        when m_score >= 4 then 'Lapsing high-value'
        else 'Lapsing one-time'
    end as rfm_segment
from scored
