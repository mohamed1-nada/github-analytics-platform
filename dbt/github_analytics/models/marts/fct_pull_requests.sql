{{ config(materialized='table') }}

-- Fact: pull requests, one row per pull request.
-- Grain: one row per (repository_id, pull_request_id).
--
-- Full rebuild on every `dbt build`. The raw table is cumulative and each
-- ingestion run re-loads a 30-day window, so the previous 1-day lookback on
-- `updated_at` only ever captured the pull requests touched on the day of
-- the build — the rest were dropped permanently. Rebuilding in full is
-- cheap at the current volume and keeps the fact reconciled with the raw
-- table (see `tests/assert_fct_pull_requests_matches_raw.sql`).
with pull_requests as (
    select *
    from {{ ref('stg_pull_requests') }}
)

select
    repository_id,
    pull_request_id,
    number,
    title,
    user_login,
    state,
    draft,
    created_at,
    updated_at,
    closed_at,
    merged_at,
    merge_commit_sha,
    (merged_at is not null) as is_merged,
    case
        when merged_at is not null
        then extract(epoch from (merged_at - created_at)) / 3600
    end as hours_to_merge,
    case
        when closed_at is not null
        then extract(epoch from (closed_at - created_at)) / 3600
    end as hours_to_close
from pull_requests
