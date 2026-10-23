select cast(event_date as date) as event_date, event_name, events, users
from {{ source('ga4', 'events_daily') }}
