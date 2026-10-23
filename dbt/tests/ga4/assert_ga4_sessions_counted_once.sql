-- Midnight-crossing sessions (845) are dated by session start and counted exactly once:
-- every daily rollup of sessions equals the number of distinct session keys, and cohort
-- sizes sum to the number of users.
with n as (select count(distinct session_key) as sessions,
                  count(distinct user_pseudo_id) as users
           from {{ ref('stg_ga4__sessions') }})
select 'daily' as mart, (select sum(sessions) from {{ ref('mart_ga4_daily') }}) as got,
       (select sessions from n) as expected
where (select sum(sessions) from {{ ref('mart_ga4_daily') }}) <> (select sessions from n)
union all
select 'funnel', (select sum(sessions) from {{ ref('mart_ga4_funnel') }}), (select sessions from n)
where (select sum(sessions) from {{ ref('mart_ga4_funnel') }}) <> (select sessions from n)
union all
select 'cohorts',
       (select sum(cohort_users) from (select distinct cohort_week, cohort_users
                                      from {{ ref('mart_ga4_cohorts') }})),
       (select users from n)
where (select sum(cohort_users) from (select distinct cohort_week, cohort_users
                                     from {{ ref('mart_ga4_cohorts') }}))
      <> (select users from n)
