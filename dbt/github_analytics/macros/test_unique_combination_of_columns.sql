{% test unique_combination_of_columns(model, combination_of_columns) %}
-- Enforces the grain of a model: no two rows may share the same key combination.
with validation as (
    select
        {% for column in combination_of_columns -%}
        {{ column }}{% if not loop.last %}, {% endif %}
        {%- endfor %},
        count(*) as n_records
    from {{ model }}
    group by
        {% for column in combination_of_columns -%}
        {{ column }}{% if not loop.last %}, {% endif %}
        {%- endfor %}
)
select *
from validation
where n_records > 1
{% endtest %}
