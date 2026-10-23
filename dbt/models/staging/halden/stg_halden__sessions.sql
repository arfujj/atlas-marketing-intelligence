select
    cast(week_start as date) as week_start,
    geo,
    cast(organic_direct_sessions as bigint) as organic_direct_sessions,
    cast(paid_sessions as bigint) as paid_sessions,
    cast(sessions as bigint) as sessions
from {{ source('halden', 'sessions_weekly') }}
