{{ config(materialized='view') }}

select
    id as repository_id,
    name,
    full_name,
    owner_login,
    description,
    language,
    created_at,
    updated_at,
    pushed_at,
    stargazers_count,
    forks_count,
    watchers_count,
    open_issues,
    default_branch,
    size,
    archived,
    topics
from {{ source('raw', 'repositories') }}
