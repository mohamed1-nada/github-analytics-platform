{{ config(materialized='table') }}

-- Fact: weekly commit activity (GitHub stats endpoint), with per-weekday split.
-- Grain: one row per (repository_id, week_start).
select
    repository_id,
    week,
    week_start,
    total_commits,
    sunday_commits,
    monday_commits,
    tuesday_commits,
    wednesday_commits,
    thursday_commits,
    friday_commits,
    saturday_commits
from {{ ref('stg_commit_activity') }}
