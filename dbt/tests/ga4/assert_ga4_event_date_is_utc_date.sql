-- Timezone handling. In this export event_date equals the UTC date of event_timestamp, so all
-- daily marts use UTC dates. If a re-extract were in a property timezone this would fail and
-- the date logic would have to change. Sessions are dated by their first event.
select 'purchase_event' as what, purchase_event_id::varchar as id
from {{ ref('stg_ga4__purchase_events') }}
where cast(event_utc at time zone 'UTC' as date) <> event_date
union all
select 'session', session_key
from {{ ref('stg_ga4__sessions') }}
where cast(session_start_utc at time zone 'UTC' as date) <> session_date
