-- Guardrail: traffic_source in this export is FIRST-USER acquisition. No GA4 mart may expose a
-- column that reads like a session or last-touch source (source, medium, channel without the
-- first_user_ prefix).
select table_name, column_name
from information_schema.columns
where table_schema = 'ga4'
  and (column_name in ('source', 'medium', 'channel', 'campaign', 'channel_group')
       or column_name like 'session_source%' or column_name like 'last_touch%')
