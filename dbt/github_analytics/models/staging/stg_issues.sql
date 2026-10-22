{{ config(materialized='view') }}

select
    id as issue_id,
    repository_id,
    number,
    title,
    user_login,
    state,
    comments,
    created_at,
    updated_at,
    closed_at
from {{ source('raw', 'issues') }}
