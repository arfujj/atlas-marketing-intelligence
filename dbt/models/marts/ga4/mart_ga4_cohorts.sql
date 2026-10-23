-- OBSERVED. Weekly acquisition cohorts WITHIN the 92-day window. A user's cohort is the week
-- of their first session in the export, which is left-censored: users active before
-- 2020-11-01 look "new" in November. Weeks start on Monday (UTC dates).
-- Later cohorts have fewer observable weeks; weeks_observable says how many.
with s as (
    select user_pseudo_id, session_key, session_date,
           date_trunc('week', session_date) as week
    from {{ ref('stg_ga4__sessions') }}
),
first_seen as (
    select user_pseudo_id, min(week) as cohort_week from s group by 1
),
activity as (
    select s.user_pseudo_id, f.cohort_week,
           cast(datediff('week', f.cohort_week, s.week) as integer) as week_number
    from s join first_seen as f using (user_pseudo_id)
    group by 1, 2, 3
),
buyers as (
    select t.user_pseudo_id, f.cohort_week,
           cast(datediff('week', f.cohort_week, date_trunc('week', t.event_date)) as integer)
               as week_number,
           count(*) as transactions, sum(t.revenue) as revenue
    from {{ ref('fct_ga4_transactions') }} as t
    join first_seen as f using (user_pseudo_id)
    group by 1, 2, 3
),
sizes as (
    select cohort_week, count(*) as cohort_users from first_seen group by 1
),
grid as (
    select a.cohort_week, a.week_number,
           count(distinct a.user_pseudo_id) as active_users
    from activity as a group by 1, 2
),
buy as (
    select cohort_week, week_number, count(distinct user_pseudo_id) as purchasers,
           sum(transactions) as transactions, sum(revenue) as revenue
    from buyers group by 1, 2
),
last_week as (select max(date_trunc('week', session_date)) as w from s)
select
    g.cohort_week,
    g.week_number,
    z.cohort_users,
    g.active_users,
    g.active_users / z.cohort_users as retention_rate,
    coalesce(b.purchasers, 0) as purchasers,
    coalesce(b.transactions, 0) as transactions,
    coalesce(b.revenue, 0) as revenue,
    cast(datediff('week', g.cohort_week, (select w from last_week)) as integer) + 1
        as weeks_observable
from grid as g
join sizes as z using (cohort_week)
left join buy as b using (cohort_week, week_number)
