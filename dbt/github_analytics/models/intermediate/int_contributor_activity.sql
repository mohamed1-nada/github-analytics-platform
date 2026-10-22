{{ config(materialized='view') }}

-- Commit activity per (repository, author) inside the loaded window.
-- Feeds dim_contributors so it can expose first/last commit dates.
select
    repository_id,
    author_login,
    count(*) as commits_in_window,
    min(commit_author_date) as first_commit_at,
    max(commit_author_date) as last_commit_at
from {{ ref('stg_commits') }}
where author_login is not null
group by 1, 2
