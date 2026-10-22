{{ config(materialized='table') }}

-- Dimension: contributors per repository.
-- Grain: one row per (repository_id, author_login).
--
-- `total_commits` comes from the GitHub contributor stats endpoint (lifetime),
-- while `commits_in_window` / first/last commit only cover the loaded window.
with stats as (
    select
        repository_id,
        author_login,
        total_commits
    from {{ ref('stg_contributors') }}
),

activity as (
    select
        repository_id,
        author_login,
        commits_in_window,
        first_commit_at,
        last_commit_at
    from {{ ref('int_contributor_activity') }}
)

select
    coalesce(stats.repository_id, activity.repository_id) as repository_id,
    coalesce(stats.author_login, activity.author_login) as author_login,
    stats.total_commits,
    coalesce(activity.commits_in_window, 0) as commits_in_window,
    activity.first_commit_at,
    activity.last_commit_at
from stats
full outer join activity
    on stats.repository_id = activity.repository_id
    and stats.author_login = activity.author_login
where coalesce(stats.author_login, activity.author_login) is not null
