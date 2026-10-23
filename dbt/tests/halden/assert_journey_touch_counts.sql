-- Unnesting a journey must yield exactly n_touches rows with positions 1..n_touches.
select journey_id, n_touches, count(*) as rows, min(touch_position) as lo, max(touch_position) as hi
from {{ ref('int_halden__journey_touches') }}
group by 1, 2
having count(*) <> n_touches or min(touch_position) <> 1 or max(touch_position) <> n_touches
