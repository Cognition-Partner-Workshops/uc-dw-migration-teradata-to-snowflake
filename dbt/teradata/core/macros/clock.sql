{% macro run_day() %}to_date('{{ var("run_date") }}'){% endmacro %}
{% macro load_timestamp() %}to_timestamp_ntz('{{ var("load_ts") }}'){% endmacro %}
{% macro batch_id() %}(select max(BATCH_ID) + 1 from {{ source('td_source', 'ETL_BATCH_CONTROL') }}){% endmacro %}
