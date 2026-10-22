{{ config(materialized='table') }}

-- Reporting aggregate joining every fact back to the repository dimension.
-- Grain: one row per repository (`repository_id`).
--
-- Note: the measures cover the *ingested window* (see `--since` on the Python
-- pipeline), not the full lifetime of the repository, except `stars`, `forks`
-- and `reported_open_issues` which come from the repository API.
with repos as (
    select
        repository_id,
        full_name,
        owner_login,
        language,
        archived,
        stargazers_count,
        forks_count,
        open_issues
    from {{ ref('dim_repositories') }}
),

commits as (
    select
        repository_id,
        sum(commits) as commits,
        count(distinct commit_date) as active_days,
        max(commit_date) as last_commit_date
    from {{ ref('fct_commits_daily') }}
    group by 1
),

pull_requests as (
    select
        repository_id,
        count(*) as pull_requests,
        count(*) filter (where is_merged) as pull_requests_merged
    from {{ ref('fct_pull_requests') }}
    group by 1
),

issues as (
    select
        repository_id,
        count(*) as issues,
        count(*) filter (where state = 'open') as issues_open
    from {{ ref('fct_issues') }}
    group by 1
)

select
    repos.repository_id,
    repos.full_name,
    repos.owner_login,
    repos.language,
    repos.archived,
    repos.stargazers_count,
    repos.forks_count,
    repos.open_issues as reported_open_issues,
    coalesce(commits.commits, 0) as commits,
    coalesce(commits.active_days, 0) as active_days,
    commits.last_commit_date,
    coalesce(pull_requests.pull_requests, 0) as pull_requests,
    coalesce(pull_requests.pull_requests_merged, 0) as pull_requests_merged,
    coalesce(issues.issues, 0) as issues,
    coalesce(issues.issues_open, 0) as issues_open
from repos
left join commits using (repository_id)
left join pull_requests using (repository_id)
left join issues using (repository_id)
