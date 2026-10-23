-- Paid spend must reconcile across every layer (staging, channel marts, geo mart, KPI mart).
with totals as (
    select 'stg_media' as layer, sum(spend) as spend from {{ ref('stg_halden__media') }}
    union all select 'fct_channel_geo_week', sum(spend) from {{ ref('fct_channel_geo_week') }}
    union all select 'fct_channel_week', sum(spend) from {{ ref('fct_channel_week') }}
    union all select 'fct_geo_week', sum(spend) from {{ ref('fct_geo_week') }}
    union all select 'mart_kpi_weekly', sum(spend) from {{ ref('mart_kpi_weekly') }}
),
ref_total as (select spend as ref_spend from totals where layer = 'stg_media')
select layer, spend, ref_spend
from totals, ref_total
where abs(spend - ref_spend) > 0.01
