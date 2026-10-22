-- Reconciliation: the daily commit fact must account for every commit in
-- the raw table.
--
-- The fact aggregates commits to one row per (repository, day), so the
-- comparable measure is the total commit count per repository, not the row
-- count. Commits without an author date are excluded on both sides, because
-- the fact cannot place them on a day.
--
-- Returns one row per repository whose totals differ; an empty result means
-- the fact is reconciled with the raw table.
with fact as (
    select
        repository_id,
        sum(commits) as commits_in_fact
    from {{ ref('fct_commits_daily') }}
    group by 1
),

raw as (
    select
        repository_id,
        count(*) as commits_in_raw
    from {{ source('raw', 'commits') }}
    where commit_author_date is not null
    group by 1
)

select
    coalesce(fact.repository_id, raw.repository_id) as repository_id,
    coalesce(fact.commits_in_fact, 0) as commits_in_fact,
    coalesce(raw.commits_in_raw, 0) as commits_in_raw,
    coalesce(raw.commits_in_raw, 0) - coalesce(fact.commits_in_fact, 0) as missing_commits
from fact
full outer join raw on fact.repository_id = raw.repository_id
where coalesce(fact.commits_in_fact, 0) <> coalesce(raw.commits_in_raw, 0)
