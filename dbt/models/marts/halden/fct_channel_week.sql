-- Grain: week × paid channel (national).
select
    week_start,
    channel,
    sum(spend) as spend,
    sum(impressions) as impressions,
    sum(clicks) as clicks,
    sum(last_click_conversions) as last_click_conversions,
    sum(last_click_revenue) as last_click_revenue,
    sum(spend) / nullif(sum(clicks), 0) as cpc,
    sum(clicks) / nullif(sum(impressions), 0) as ctr,
    1000 * sum(spend) / nullif(sum(impressions), 0) as cpm
from {{ ref('fct_channel_geo_week') }}
group by 1, 2
