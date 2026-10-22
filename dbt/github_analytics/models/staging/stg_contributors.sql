{{ config(materialized='view') }}

select
    repository_id,
    author_login,
    total_commits
from {{ source('raw', 'contributors') }}
