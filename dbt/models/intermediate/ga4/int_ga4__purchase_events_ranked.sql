-- Documented dedup rule (docs/decisions.md D-011):
--   * Valid transaction ids: keep the EARLIEST purchase event per transaction_id
--     (ties broken by higher revenue, then purchase_event_id). Later events with the same id
--     are duplicates (re-fired tags, page reloads) and are excluded from revenue.
--   * '(not set)' and NULL ids cannot be deduplicated. They are kept as `unidentified`
--     events and reported separately; they are NOT added to deduplicated revenue.
select
    *,
    case when transaction_id_status = 'valid' then row_number() over (
        partition by transaction_id
        order by event_utc, purchase_revenue_usd desc, purchase_event_id
    ) end as duplicate_rank,
    case
        when transaction_id_status <> 'valid' then 'unidentified'
        when row_number() over (
            partition by transaction_id
            order by event_utc, purchase_revenue_usd desc, purchase_event_id
        ) = 1 then 'kept'
        else 'duplicate'
    end as dedup_status
from {{ ref('stg_ga4__purchase_events') }}
