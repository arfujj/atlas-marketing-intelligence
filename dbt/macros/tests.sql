{# Generic tests used across the project (no external packages, so `dbt build` runs offline). #}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}

{% test non_negative(model, column_name) %}
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}

{% test between(model, column_name, min_value, max_value) %}
select * from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}

{# Row count of `model` must equal row count of `compare_model` (optionally filtered). #}
{% test same_row_count(model, compare_model, where_clause="true") %}
with a as (select count(*) as n from {{ model }}),
     b as (select count(*) as n from {{ compare_model }} where {{ where_clause }})
select a.n as model_rows, b.n as compare_rows from a, b where a.n <> b.n
{% endtest %}
