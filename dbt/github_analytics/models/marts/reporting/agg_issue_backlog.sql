{{ config(materialized='table') }}

-- Reporting aggregate: issue backlog health per repository.
--
-- Grain: one row per repository (`repository_id`).
--
-- The spine is `dim_repositories`, not the fact: a repository with no issues
-- in the ingested window still gets a row of zeros instead of disappearing
-- from the dashboard, where "absent" reads as "not tracked".
--
-- `as_of` is the watermark of the ingested data (the newest `updated_at` in
-- the raw issue table). Ages are measured against that watermark rather than
-- against `now()`, so the numbers stay stable for a given data set and the
-- dashboard can state which instant they describe.
--
-- The backlog measures (`open_issues`, `median_open_age_days`,
-- `oldest_open_created_at`) describe the *open* issues only; the throughput
-- measures (`close_rate`, `median_hours_to_close`) describe the whole
-- ingested history.
with watermark as (
    select max(updated_at) as as_of
    from {{ source('raw', 'issues') }}
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
),

per_repository as (
    select
        repository_id,
        count(*) as total_issues,
        count(*) filter (where state = 'open') as open_issues,
        count(*) filter (where state = 'closed') as closed_issues,
        count(*) filter (where state = 'open' and closed_at is null) as open_issues_unresolved,
        -- Age buckets for the open backlog.
        count(*) filter (
            where state = 'open'
                and (select as_of from watermark) - created_at > interval '90 days'
        ) as open_issues_over_90d,
        count(*) filter (
            where state = 'open'
                and (select as_of from watermark) - created_at > interval '30 days'
                and (select as_of from watermark) - created_at <= interval '90 days'
        ) as open_issues_30_to_90d,
        count(*) filter (
            where state = 'open'
                and (select as_of from watermark) - created_at <= interval '30 days'
        ) as open_issues_under_30d,
        min(created_at) filter (where state = 'open') as oldest_open_created_at,
        percentile_cont(0.5) within group (
            order by extract(epoch from ((select as_of from watermark) - created_at)) / 86400.0
        ) filter (where state = 'open') as median_open_age_days,
        percentile_cont(0.5) within group (
            order by hours_to_close
        ) filter (where hours_to_close is not null) as median_hours_to_close,
        sum(comments) as total_comments,
        avg(comments) as avg_comments_per_issue
    from {{ ref('fct_issues') }}
    group by 1
),

backlog as (
    select
        repository_id,
        total_issues,
        open_issues,
        closed_issues,
        open_issues_unresolved,
        open_issues_under_30d,
        open_issues_30_to_90d,
        open_issues_over_90d,
        oldest_open_created_at,
        median_open_age_days,
        median_hours_to_close,
        total_comments,
        avg_comments_per_issue
    from per_repository
)

select
    repositories.repository_id,
    repositories.full_name,
    repositories.owner_login,
    repositories.language,
    (select as_of from watermark) as as_of,
    coalesce(backlog.total_issues, 0) as total_issues,
    coalesce(backlog.open_issues, 0) as open_issues,
    coalesce(backlog.closed_issues, 0) as closed_issues,
    coalesce(backlog.open_issues_unresolved, 0) as open_issues_unresolved,
    round(100.0 * backlog.closed_issues / nullif(backlog.total_issues, 0), 2) as close_rate_pct,
    coalesce(backlog.open_issues_under_30d, 0) as open_issues_under_30d,
    coalesce(backlog.open_issues_30_to_90d, 0) as open_issues_30_to_90d,
    coalesce(backlog.open_issues_over_90d, 0) as open_issues_over_90d,
    backlog.oldest_open_created_at,
    round(backlog.median_open_age_days::numeric, 1) as median_open_age_days,
    round(backlog.median_hours_to_close::numeric, 2) as median_hours_to_close,
    coalesce(backlog.total_comments, 0) as total_comments,
    round(backlog.avg_comments_per_issue::numeric, 2) as avg_comments_per_issue
from repositories
left join backlog using (repository_id)
