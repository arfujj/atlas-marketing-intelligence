-- Paid sessions are defined as platform clicks; sessions = organic/direct + paid.
select week_start, geo, paid_sessions, paid_clicks, sessions, organic_direct_sessions
from {{ ref('fct_geo_week') }}
where paid_sessions <> paid_clicks
   or sessions <> organic_direct_sessions + paid_sessions
