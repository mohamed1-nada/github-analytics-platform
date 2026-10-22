-- Reconciliation: the issue fact must hold every issue that the raw table
-- holds, for every repository.
--
-- The raw `issues` table already excludes pull requests (the extractor skips
-- any issue payload carrying a `pull_request` key), so the fact and the raw
-- table must match one-to-one.
--
-- Returns one row per repository whose counts differ; an empty result means
-- the fact is reconciled with the raw table.
with fact as (
    select
        repository_id,
        count(*) as rows_in_fact
    from {{ ref('fct_issues') }}
    group by 1
),

raw as (
    select
        repository_id,
        count(*) as rows_in_raw
    from {{ source('raw', 'issues') }}
    group by 1
)

select
    coalesce(fact.repository_id, raw.repository_id) as repository_id,
    coalesce(fact.rows_in_fact, 0) as rows_in_fact,
    coalesce(raw.rows_in_raw, 0) as rows_in_raw,
    coalesce(raw.rows_in_raw, 0) - coalesce(fact.rows_in_fact, 0) as missing_rows
from fact
full outer join raw on fact.repository_id = raw.repository_id
where coalesce(fact.rows_in_fact, 0) <> coalesce(raw.rows_in_raw, 0)
