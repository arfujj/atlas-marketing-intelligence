{# Use the configured schema name as-is (halden, halden_stg, ga4, ...) instead of prefixing
   it with the target schema. Keeps serving-database names stable for the API. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
