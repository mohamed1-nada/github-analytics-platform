{{ config(materialized='view') }}

select
    id as pull_request_id,
    repository_id,
    number,
    title,
    user_login,
    state,
    created_at,
    updated_at,
    closed_at,
    merged_at,
    draft,
    merge_commit_sha
from {{ source('raw', 'pull_requests') }}
