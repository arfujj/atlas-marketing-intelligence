-- Grain: week × region × paid channel. Media delivery (SIMULATED, platform-reported) plus
-- last-click credit (ATTRIBUTED, not causal).
select
    m.week_start,
    m.geo,
    m.channel,
    m.spend,
    m.impressions,
    m.clicks,
    coalesce(lc.last_click_conversions, 0) as last_click_conversions,
    coalesce(lc.last_click_revenue, 0) as last_click_revenue
from {{ ref('stg_halden__media') }} as m
left join {{ ref('int_halden__last_click') }} as lc
    on lc.week_start = m.week_start and lc.geo = m.geo and lc.channel = m.channel
