{{ config(materialized='table') }}

-- Dimension: repositories.
-- Grain: one row per repository (`repository_id`).
select
    repository_id,
    name,
    full_name,
    owner_login,
    description,
    language,
    stargazers_count,
    forks_count,
    watchers_count,
    open_issues,
    default_branch,
    size,
    archived,
    topics,
    created_at,
    updated_at,
    pushed_at
from {{ ref('stg_repositories') }}
