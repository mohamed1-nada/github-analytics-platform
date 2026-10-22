{{ config(materialized='table') }}

-- Reporting aggregate over fct_pull_requests.
-- Grain: one row per repository (`repository_id`).
--
-- The spine is `dim_repositories`, not the fact: a repository with no pull
-- requests in the ingested window still gets a row of zeros instead of
-- disappearing from the dashboard, where "absent" reads as "not tracked".
with summary as (
    select
        repository_id,
        count(*) as total_pull_requests,
        count(*) filter (where state = 'open') as open_pull_requests,
        count(*) filter (where is_merged) as merged_pull_requests,
        count(*) filter (where not is_merged and state = 'closed') as closed_unmerged_pull_requests,
        count(*) filter (where draft) as draft_pull_requests,
        round(avg(hours_to_merge) filter (where is_merged)::numeric, 2) as avg_hours_to_merge,
        round(
            (percentile_cont(0.5) within group (order by hours_to_merge)
                filter (where is_merged))::numeric,
            2
        ) as median_hours_to_merge
    from {{ ref('fct_pull_requests') }}
    group by 1
),

repositories as (
    select
        repository_id,
        full_name,
        owner_login,
        language
    from {{ ref('dim_repositories') }}
)

select
    repositories.repository_id,
    repositories.full_name,
    repositories.owner_login,
    repositories.language,
    coalesce(summary.total_pull_requests, 0) as total_pull_requests,
    coalesce(summary.open_pull_requests, 0) as open_pull_requests,
    coalesce(summary.merged_pull_requests, 0) as merged_pull_requests,
    coalesce(summary.closed_unmerged_pull_requests, 0) as closed_unmerged_pull_requests,
    coalesce(summary.draft_pull_requests, 0) as draft_pull_requests,
    summary.avg_hours_to_merge,
    summary.median_hours_to_merge
from repositories
left join summary using (repository_id)
