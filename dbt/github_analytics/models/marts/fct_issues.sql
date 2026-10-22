{{ config(materialized='table') }}

-- Fact: issues, one row per issue (pull requests are excluded upstream).
-- Grain: one row per (repository_id, issue_id).
--
-- Full rebuild on every `dbt build`, for the same reason as
-- `fct_pull_requests`: a 1-day lookback on a cumulative raw table dropped
-- the issues that were not touched on the day of the build.
with issues as (
    select *
    from {{ ref('stg_issues') }}
)

select
    repository_id,
    issue_id,
    number,
    title,
    user_login,
    state,
    comments,
    created_at,
    updated_at,
    closed_at,
    (closed_at is not null) as is_closed,
    case
        when closed_at is not null
        then extract(epoch from (closed_at - created_at)) / 3600
    end as hours_to_close
from issues
