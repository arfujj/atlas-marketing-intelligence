select
    cast(week_start as date) as week_start,
    geo,
    channel,
    cast(spend as double) as spend,
    cast(impressions as bigint) as impressions,
    cast(clicks as bigint) as clicks
from {{ source('halden', 'media_weekly') }}
