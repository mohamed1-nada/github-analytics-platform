-- Reconciliation: the pull request fact must hold every pull request that
-- the raw table holds, for every repository.
--
-- This test exists because the fact used to be built incrementally with a
-- 1-day lookback on `updated_at` against a cumulative raw table, which
-- dropped ~84% of the pull requests. The failure mode was silent: the model
-- built, the grain test passed, and only the row counts disagreed.
--
-- Returns one row per repository whose counts differ; an empty result means
-- the fact is reconciled with the raw table.
with fact as (
    select
        repository_id,
        count(*) as rows_in_fact
    from {{ ref('fct_pull_requests') }}
    group by 1
),

raw as (
    select
        repository_id,
        count(*) as rows_in_raw
    from {{ source('raw', 'pull_requests') }}
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
