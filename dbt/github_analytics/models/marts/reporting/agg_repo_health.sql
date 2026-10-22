{{ config(materialized='table') }}

-- Reporting aggregate: a composite health score per repository.
--
-- Grain: one row per repository (`repository_id`).
--
-- The score is *relative to the tracked portfolio*: every component is the
-- percentile rank of a raw measure among all tracked repositories, scaled
-- to 0-100. A score of 80 therefore means "in the top quintile of the
-- tracked set", not "80% healthy". Use the component columns to understand
-- why a repository scores the way it does — the score itself is a summary.
--
-- Components and weights:
--
--   | component        | raw measure                          | weight |
--   |------------------|--------------------------------------|--------|
--   | activity         | commits in the ingested window       | 0.35   |
--   | community        | distinct contributors                | 0.25   |
--   | backlog          | issue close rate (triage effective)  | 0.20   |
--   | popularity       | stargazers                           | 0.20   |
--
-- A repository with no issues at all gets the maximum backlog score: there
-- is no backlog to triage. `health_band` turns the score into the four
-- labels used to colour the dashboard.
with metrics as (
    select
        repository_id,
        full_name,
        owner_login,
        language,
        stargazers_count,
        forks_count,
        coalesce(commits, 0) as commits,
        coalesce(pull_requests, 0) as pull_requests,
        coalesce(issues, 0) as issues,
        coalesce(issues_open, 0) as issues_open,
        last_commit_date
    from {{ ref('agg_repository_metrics') }}
),

contributors as (
    select
        repository_id,
        coalesce(contributors, 0) as contributors,
        coalesce(top10_share_pct, 0) as top10_share_pct
    from {{ ref('agg_contributor_concentration') }}
),

backlog as (
    select
        repository_id,
        coalesce(close_rate_pct, 100) as close_rate_pct,
        coalesce(median_open_age_days, 0) as median_open_age_days
    from {{ ref('agg_issue_backlog') }}
),

scored as (
    select
        metrics.*,
        coalesce(contributors.contributors, 0) as contributors,
        coalesce(contributors.top10_share_pct, 0) as top10_share_pct,
        coalesce(backlog.close_rate_pct, 100) as close_rate_pct,
        coalesce(backlog.median_open_age_days, 0) as median_open_age_days
    from metrics
    left join contributors using (repository_id)
    left join backlog using (repository_id)
),

percentiles as (
    select
        *,
        round((100.0 * percent_rank() over (order by commits))::numeric, 2) as activity_score,
        round((100.0 * percent_rank() over (order by contributors))::numeric, 2) as community_score,
        round((100.0 * percent_rank() over (order by close_rate_pct))::numeric, 2) as backlog_score,
        round((100.0 * percent_rank() over (order by stargazers_count))::numeric, 2) as popularity_score
    from scored
)

select
    repository_id,
    full_name,
    owner_login,
    language,
    stargazers_count,
    forks_count,
    commits,
    pull_requests,
    issues,
    issues_open,
    contributors,
    top10_share_pct,
    close_rate_pct,
    median_open_age_days,
    last_commit_date,
    round(activity_score, 2) as activity_score,
    round(community_score, 2) as community_score,
    round(backlog_score, 2) as backlog_score,
    round(popularity_score, 2) as popularity_score,
    round(
        0.35 * activity_score
        + 0.25 * community_score
        + 0.20 * backlog_score
        + 0.20 * popularity_score,
        2
    ) as health_score,
    case
        when 0.35 * activity_score
           + 0.25 * community_score
           + 0.20 * backlog_score
           + 0.20 * popularity_score >= 75 then 'Excellent'
        when 0.35 * activity_score
           + 0.25 * community_score
           + 0.20 * backlog_score
           + 0.20 * popularity_score >= 50 then 'Good'
        when 0.35 * activity_score
           + 0.25 * community_score
           + 0.20 * backlog_score
           + 0.20 * popularity_score >= 25 then 'Fair'
        else 'At risk'
    end as health_band
from percentiles
