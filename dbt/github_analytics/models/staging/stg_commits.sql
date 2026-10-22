{{ config(materialized='view') }}

select
    repository_id,
    sha,
    author_login,
    author_name,
    committer_login,
    commit_author_date,
    commit_committer_date,
    commit_message
from {{ source('raw', 'commits') }}
