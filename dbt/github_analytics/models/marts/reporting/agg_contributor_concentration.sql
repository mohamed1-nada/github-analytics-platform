{{ config(materialized='table') }}

-- Reporting aggregate: how concentrated is a repository's contribution?
--
-- Grain: one row per repository (`repository_id`).
--
-- The measures answer the "bus factor" question: if the top contributor
-- disappears, how much of the project moves with them?
--
--   * `top1_share_pct` / `top10_share_pct` — share of commits made by the
--     single most active contributor / by the ten most active ones.
--   * `gini_coefficient` — 0 means every contributor commits equally,
--     1 means one contributor made every commit. Computed with the
--     rank-sum formula over the commits per contributor sorted ascending:
--     G = (2 * sum(i * x_i)) / (n * sum(x_i)) - (n + 1) / n. Because the
--     ranking below is descending (1 = most active), the ascending rank is
--     recovered as `i = n - d + 1`, which folds the formula into
--     G = (n + 1) / n - (2 * sum(d * x_d)) / (n * sum(x)).
--   * `bus_factor` — how many people would have to disappear before the
--     project loses its momentum: 1 (single maintainer), 2 (the top
--     contributor made half the commits), 3 (the top ten made 80% of them)
--     or 4 (a broad base).
--
-- `total_commits` is the lifetime count reported by the GitHub contributor
-- stats endpoint, so it is not limited to the ingested window.
-- Contributors whose lifetime count is unknown are treated as zero commits,
-- which makes the concentration figures conservative (they understate the
-- gap between the top contributor and the rest).
with ranked as (
    select
        repository_id,
        author_login,
        coalesce(total_commits, 0) as total_commits,
        coalesce(commits_in_window, 0) as commits_in_window,
        row_number() over (
            partition by repository_id
            order by coalesce(total_commits, 0) desc, author_login asc
        ) as contribution_rank
    from {{ ref('dim_contributors') }}
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
        count(*) as contributors,
        count(*) filter (where commits_in_window > 0) as active_contributors,
        sum(total_commits) as total_commits,
        max(total_commits) as top1_commits,
        sum(total_commits) filter (where contribution_rank <= 10) as top10_commits,
        percentile_cont(0.5) within group (
            order by total_commits
        ) as median_commits_per_contributor,
        -- Gini coefficient over the per-contributor commit counts.
        case
            when count(*) > 0 and sum(total_commits) > 0
            then (
                (count(*) + 1.0) / count(*)
            ) - (
                2.0 * sum(contribution_rank * total_commits)
                / (count(*) * sum(total_commits))
            )
        end as gini_coefficient
    from ranked
    group by 1
),

shares as (
    select
        repository_id,
        contributors,
        active_contributors,
        total_commits,
        top1_commits,
        top10_commits,
        round(100.0 * top1_commits / nullif(total_commits, 0), 2) as top1_share_pct,
        round(100.0 * top10_commits / nullif(total_commits, 0), 2) as top10_share_pct,
        round(median_commits_per_contributor::numeric, 2) as median_commits_per_contributor,
        round(gini_coefficient, 4) as gini_coefficient
    from per_repository
),

concentration as (
    select
        repository_id,
        contributors,
        active_contributors,
        total_commits,
        top1_commits,
        top10_commits,
        top1_share_pct,
        top10_share_pct,
        median_commits_per_contributor,
        gini_coefficient,
        contributors = 1 as is_single_maintainer,
        case
            -- No lifetime commit count was ingested for this repository (the
            -- contributors-stats endpoint failed or is still computing), so
            -- the concentration is unknown rather than "broad based".
            when total_commits = 0 then null
            when contributors = 1 then 1
            when top1_share_pct >= 50 then 2
            when top10_share_pct >= 80 then 3
            else 4
        end as bus_factor
    from shares
)

select
    concentration.repository_id,
    repositories.full_name,
    repositories.owner_login,
    repositories.language,
    concentration.contributors,
    concentration.active_contributors,
    concentration.total_commits,
    concentration.top1_commits,
    concentration.top10_commits,
    concentration.top1_share_pct,
    concentration.top10_share_pct,
    concentration.median_commits_per_contributor,
    concentration.gini_coefficient,
    concentration.is_single_maintainer,
    concentration.bus_factor
from concentration
left join repositories using (repository_id)
