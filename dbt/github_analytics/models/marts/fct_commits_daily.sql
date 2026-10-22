{{ config(materialized='table') }}

-- Fact: commits per repository per day.
-- Grain: one row per (repository_id, commit_date).
--
-- Full rebuild on every `dbt build`. The raw table is cumulative and each
-- ingestion run re-loads a 30-day window, so a date-windowed incremental
-- filter (the previous 3-day lookback) silently dropped every commit whose
-- last touch fell between two builds. Rebuilding the whole table costs a
-- few seconds at the current volume and removes that whole class of bug.
with commits as (
    select
        repository_id,
        commit_author_date::date as commit_date,
        author_login,
        committer_login
    from {{ ref('stg_commits') }}
    where commit_author_date is not null
)

select
    repository_id,
    commit_date,
    count(*) as commits,
    count(distinct author_login) as distinct_authors,
    count(distinct committer_login) as distinct_committers
from commits
group by 1, 2
