# GitHub Analytics (dbt)

Transforms the raw tables loaded by the Python pipeline into a documented
star schema plus reporting aggregates.

## Layers

| Layer | Folder | Materialization | Purpose |
|---|---|---|---|
| Staging | `models/staging/` | view | 1:1 with raw sources: renames and casts only |
| Intermediate | `models/intermediate/` | view | Reusable joins/derivations consumed by marts |
| Marts | `models/marts/` | table | Dimensions and facts (star schema) |
| Reporting | `models/marts/reporting/` | table | Aggregates / KPIs for dashboards |

## Lineage

```
raw.repositories ─► stg_repositories ─┬─► dim_repositories ─────────────┐
                                      │                                 │
raw.commits ──────► stg_commits ──┬───┼─► fct_commits_daily ────────┐   │
                                  │   │                             │   │
                                  │   └─► int_contributor_activity ─┼──►│
                                  │              │                  │   │
raw.contributors ─► stg_contributors ────────────┴─► dim_contributors│   │
                                                                      │   │
raw.pull_requests ► stg_pull_requests ─► fct_pull_requests ──┬────────┼──►│
                                                              │        │   │
                                                        agg_pull_request_summary
                                                              │        │   │
raw.issues ───────► stg_issues ────────► fct_issues ──────────┼────────┼──►│
                                                              │        │   │
raw.commit_activity ► stg_commit_activity ► fct_commit_activity_weekly┼──►│
                                                                       │   │
                                                          agg_repository_metrics
```

## Grain contract

Every model declares its grain in a description **and** enforces it with the
`unique_combination_of_columns` test (see `macros/`), so a bad join that
duplicates rows fails the build instead of silently inflating metrics.

| Model | Grain | Key measures |
|---|---|---|
| `dim_repositories` | repository | metadata, stars, forks |
| `dim_contributors` | repository + author | lifetime commits, window activity |
| `fct_commits_daily` | repository + day | commits, distinct authors |
| `fct_pull_requests` | repository + pull request | `hours_to_merge`, `hours_to_close`, `is_merged` |
| `fct_issues` | repository + issue | `hours_to_close`, `is_closed` |
| `fct_commit_activity_weekly` | repository + week | weekly totals per weekday |
| `agg_pull_request_summary` | repository | avg/median hours to merge |
| `agg_repository_metrics` | repository | commits, PRs, issues per repository |
| `agg_contributor_concentration` | repository | top-1/top-10 share, Gini, bus factor |
| `agg_activity_trend` | repository + week | commits, PRs created/merged, issues created/closed |
| `agg_issue_backlog` | repository | open issues, median open age, close rate |
| `agg_repo_health` | repository | composite health score and its components |

## Build strategy

The three row-level facts (`fct_commits_daily`, `fct_pull_requests`,
`fct_issues`) are **full-rebuild tables**: every `dbt build` recomputes them
from the raw tables.

They used to be `incremental` with `delete+insert` and a short lookback
(3 days for commits, 1 day for issues and pull requests). That was wrong for
this pipeline, and silently so:

- the raw tables are **cumulative** — every ingestion run re-loads a
  `LOOKBACK_DAYS` window on top of what is already there;
- the lookback was anchored on `max(updated_at)` of the *target*, which
  advances on every build.

So each build only ever captured the entities touched on the day of the
build, and everything in between the builds was dropped **permanently**. At
the time of the fix the pull request fact held 16% of the raw pull requests
and covered 140 of 175 repositories; the reporting aggregates built on top
of it were ranking repositories by a sample of their activity.

At the current volume (~136k pull requests, ~61k issues, ~116k commits) a
full rebuild takes a couple of seconds, so the incremental machinery bought
nothing but the bug.

### Reconciliation tests

`tests/` holds singular tests that assert each fact still accounts for
every row in its raw table, per repository:

- `assert_fct_pull_requests_matches_raw.sql`
- `assert_fct_issues_matches_raw.sql`
- `assert_fct_commits_daily_matches_raw.sql`

They fail the build when a repository's counts drift apart, so a future
change that reintroduces a lossy filter is caught immediately instead of
quietly emptying the warehouse.

> These tests are strict: they compare the fact against the raw table *as it
> is at build time*. Running `dbt build` while ingestion is still writing
> (the Airflow DAG always builds after ingestion has finished) can make them
> fail with a small, transient difference.

Run `dbt build --full-refresh` to rebuild everything from scratch.

## Commands

```bash
cd dbt/github_analytics

# using the in-repo profile (reads the same .env variables as the pipeline)
set -a && source ../../.env && set +a
uv run dbt build --profiles-dir .
uv run dbt source freshness --profiles-dir .
uv run dbt docs generate --profiles-dir . && uv run dbt docs serve --profiles-dir .
```

`dbt build` runs models **and** tests (grain, relationships, accepted values,
source freshness is a separate command).

## Conventions

- Sources are declared in `models/staging/sources.yml` with a `loaded_at_field`
  so `dbt source freshness` can detect a stalled ingestion.
- Staging models never join or aggregate — that is what intermediate/marts are for.
- Facts store foreign keys to dimensions (`repository_id`) and never duplicate
  descriptive attributes, except where a reporting mart intentionally denormalizes.
