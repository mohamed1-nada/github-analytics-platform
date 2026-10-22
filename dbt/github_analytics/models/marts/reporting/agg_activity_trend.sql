{{ config(materialized='table') }}

-- Reporting aggregate: weekly activity per repository.
--
-- Grain: one row per (repository_id, week_start).
--
-- `week_start` is an ISO week (Monday), produced by `date_trunc('week', ...)`.
-- Note that this differs from `fct_commit_activity_weekly`, which keeps the
-- GitHub stats endpoint's Sunday-based weeks.
--
-- Every measure is a *flow* (events that happened inside the week), except
-- `active_authors`, which counts distinct people who authored at least one
-- commit that week — a stock, not a flow.
--
-- The spine is the set of (repository, week) pairs where the repository had
-- *any* activity, so a quiet week is simply absent rather than a row of
-- zeros. Cross-repository charts should aggregate with `sum()`; a single
-- repository's history is a continuous line because its active weeks are
-- contiguous.
with commit_agg as (
    select
        repository_id,
        date_trunc('week', commit_date)::date as week_start,
        sum(commits) as commits
    from {{ ref('fct_commits_daily') }}
    group by 1, 2
),

author_agg as (
    select
        repository_id,
        date_trunc('week', commit_author_date)::date as week_start,
        count(distinct author_login) as active_authors
    from {{ ref('stg_commits') }}
    where commit_author_date is not null
    group by 1, 2
),

pr_created as (
    select
        repository_id,
        date_trunc('week', created_at)::date as week_start,
        count(*) as prs_created
    from {{ ref('fct_pull_requests') }}
    where created_at is not null
    group by 1, 2
),

pr_merged as (
    select
        repository_id,
        date_trunc('week', merged_at)::date as week_start,
        count(*) as prs_merged
    from {{ ref('fct_pull_requests') }}
    where merged_at is not null
    group by 1, 2
),

issue_created as (
    select
        repository_id,
        date_trunc('week', created_at)::date as week_start,
        count(*) as issues_created
    from {{ ref('fct_issues') }}
    where created_at is not null
    group by 1, 2
),

issue_closed as (
    select
        repository_id,
        date_trunc('week', closed_at)::date as week_start,
        count(*) as issues_closed
    from {{ ref('fct_issues') }}
    where closed_at is not null
    group by 1, 2
),

-- Spine: every (repository, week) pair with at least one event.
spine as (
    select repository_id, week_start from commit_agg
    union
    select repository_id, week_start from pr_created
    union
    select repository_id, week_start from pr_merged
    union
    select repository_id, week_start from issue_created
    union
    select repository_id, week_start from issue_closed
),

-- Repository labels, so the aggregate can be charted and filtered without
-- a join back to the dimension.
repositories as (
    select
        repository_id,
        full_name,
        owner_login,
        language
    from {{ ref('dim_repositories') }}
)

select
    spine.repository_id,
    repositories.full_name,
    repositories.owner_login,
    repositories.language,
    spine.week_start,
    coalesce(commit_agg.commits, 0) as commits,
    coalesce(author_agg.active_authors, 0) as active_authors,
    coalesce(pr_created.prs_created, 0) as prs_created,
    coalesce(pr_merged.prs_merged, 0) as prs_merged,
    coalesce(issue_created.issues_created, 0) as issues_created,
    coalesce(issue_closed.issues_closed, 0) as issues_closed,
    coalesce(pr_created.prs_created, 0) - coalesce(pr_merged.prs_merged, 0) as net_pr_flow
from spine
left join commit_agg
    on commit_agg.repository_id = spine.repository_id
    and commit_agg.week_start = spine.week_start
left join author_agg
    on author_agg.repository_id = spine.repository_id
    and author_agg.week_start = spine.week_start
left join pr_created
    on pr_created.repository_id = spine.repository_id
    and pr_created.week_start = spine.week_start
left join pr_merged
    on pr_merged.repository_id = spine.repository_id
    and pr_merged.week_start = spine.week_start
left join issue_created
    on issue_created.repository_id = spine.repository_id
    and issue_created.week_start = spine.week_start
left join issue_closed
    on issue_closed.repository_id = spine.repository_id
    and issue_closed.week_start = spine.week_start
left join repositories
    on repositories.repository_id = spine.repository_id
