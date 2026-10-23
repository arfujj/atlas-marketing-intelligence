-- The data-quality findings documented in docs/ga4-extraction.md must be reproduced exactly
-- by the build. If the extract changes, this test fails and the docs must be updated.
with expected(check_id, expected_value) as (
    values
        ('sessions', 360129.0), ('users', 270154.0), ('purchase_events', 5692.0),
        ('tx_not_set', 883.0), ('tx_null', 23.0), ('tx_duplicates', 335.0),
        ('transactions', 4451.0), ('revenue_naive', 362165.0), ('revenue_dedup', 307640.0),
        ('revenue_unidentified', 31817.0), ('midnight_sessions', 845.0),
        ('first_user_data_deleted', 22236.0), ('first_user_other', 97289.0)
)
select e.check_id, e.expected_value, q.value
from expected as e
left join {{ ref('mart_ga4_data_quality') }} as q using (check_id)
where q.value is null or abs(q.value - e.expected_value) > 0.5
union all
-- sessions and users must also reconcile to the dataset totals extracted from BigQuery
select check_id, reference_value, value
from {{ ref('mart_ga4_data_quality') }}
where reference_value is not null and value <> reference_value
