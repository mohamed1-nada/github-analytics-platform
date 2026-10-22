# GitHub Open Source Analytics

Ingestion and analytics pipeline for GitHub repository data (commits, issues,
pull requests, contributors, commit activity), loaded into PostgreSQL and
transformed with dbt.

## Architecture

```
extraction/          GitHub API client + per-entity extractors (generator-based)
database/init/       Postgres connection, batch loader with upserts, table DDL runner
database/schemas/    Raw table DDL
dbt/github_analytics/dbt project: sources -> staging views -> mart tables
dags/                Airflow DAGs (github_analytics)
docker/              Dockerfile + uv-exported requirements for the Airflow image
pipeline.py          Step registry + orchestration
repos.py             Repository list resolution (shared by CLI and DAG)
main.py              CLI entrypoint
config.py            Central environment-based settings
```

## Setup

1. `uv sync --dev`
2. Copy `.env.example` to `.env` and fill in values.
3. `docker compose up -d` to start Postgres + pgAdmin (UI on
   http://localhost:8081).
4. Create tables: `uv run python -m database.init.create_tables`

## Choosing repositories

Repositories live in `repos.yaml`:

```yaml
repos:            # exact repositories (OWNER/NAME)
  - torvalds/linux
  - facebook/react

topics:           # auto-discover the top-starred repos per GitHub topic
  - name: data-engineering
    top: 5
```

You can add as many repos and topics as you want. Topic discovery uses the
GitHub Search API, so each topic costs one API request per run.

Topic discovery keeps only analyzable repositories: results are filtered to
`stars:>=1000`, `archived:false` and `fork:false`, and are fetched most-starred
first. Repositories that appear in several topics (or in the direct list) are
deduplicated, so the final count is lower than the sum of the topics.

The checked-in configuration defines ~31 topics across 18 tracks (data
engineering, ML/AI, web, DevOps, databases, systems, mobile, security, testing,
observability, cloud, visualization, messaging, blockchain, gamedev, embedded,
IoT), which resolves to roughly 170-190 unique repositories at `top: 8`.

Predicted API cost per run: a repository costs roughly 15-25 requests (one
paginated request per 100 commits/PRs/issues plus two stats calls), all under
the authenticated limit of 5,000 requests/hour. To stay inside it, prefer
raising `top` on a few focused topics over adding many topics; the client
sleeps until the quota resets whenever the limit is hit.

`<1,000`-star projects and forks are excluded by design; lower the threshold in
`extraction/discovery.py` (`SEARCH_QUALIFIERS`) if you want a longer tail.

## Running the pipeline

```bash
# everything from repos.yaml (direct list + topic discovery)
uv run python main.py

# preview which repos would be ingested, without loading anything
uv run python main.py --list-only

# direct repos only, skip topic discovery
uv run python main.py --no-topics

# ad-hoc repos (overrides repos.yaml)
uv run python main.py --repo torvalds/linux --repo rust-lang/rust

# custom window, one step only
uv run python main.py --since 2025-09-01 --step commits
```

The pipeline exits with a non-zero code if any repository fails, so it is safe
to run from cron. For scheduled orchestration, use the Airflow DAG below.

## Airflow (orchestration)

The `github_analytics` DAG (`dags/github_analytics.py`) runs the same pipeline
on a schedule:

```
init_tables -> list_repos -> ingest_repo (mapped, one task per repository) -> dbt build
```

- **Schedule:** daily at 04:00 UTC, no catchup. Each run ingests the previous
  data interval; manual runs without an interval fall back to `LOOKBACK_DAYS`.
- **Granularity:** one mapped task per repository (from `repos.yaml`), so a
  failing repo retries without re-running the others. `max_active_tasks=4`
  keeps GitHub API usage in check.
- **Idempotent:** loaders are upserts, so re-runs and backfills are safe.
- Airflow runs in Docker (LocalExecutor) with the project's dependencies
  baked into a custom image; the repo itself is mounted, so DAG/pipeline
  edits apply without rebuilding.

### Running it

```bash
# first run: builds the image, creates the metadata DB, migrates, adds admin
docker compose up airflow-db-create airflow-init

# start the stack (scheduler, dag-processor, api-server, triggerer)
docker compose up -d

# UI: http://localhost:8090  (default login: airflow / airflow)
# pgAdmin (unchanged):       http://localhost:8081

# trigger a run from inside a container
docker compose exec airflow-scheduler airflow dags trigger github_analytics

# smoke-test a couple of repos without editing repos.yaml
docker compose exec airflow-scheduler airflow dags trigger github_analytics \
  --run-id smoke --conf '{"repos": ["apache/airflow", "dbt-labs/dbt-core"]}'

# watch task states / logs
docker compose exec airflow-scheduler airflow dags list
docker compose exec airflow-scheduler airflow tasks states-for-dag-run github_analytics <run_id>
docker compose exec airflow-scheduler airflow dags state github_analytics <run_id>
```

`list_repos` accepts a `repos` list in the run conf (`{"repos": [...]}`) that
overrides `repos.yaml` for that run only — useful for smoke tests and for
backfilling a single repository without touching the tracked config.

At ~190 repositories with `max_active_tasks=4`, a full run takes roughly 1-2
hours. Because the run outlives the hourly API window, heavy repositories may
occasionally wait for a rate-limit reset; `ingest_repo` has a 90-minute
execution timeout to absorb that. A single repository failing after its retries
fails the run and skips `dbt_build` (the strict default); check the failing
task's log for the specific step and repo.

**API budget:** a full ~190-repo run consumes essentially the whole 5,000
requests/hour allowance, so expect one rate-limit wait per run (the client
sleeps until the window resets rather than failing). The cheapest lever is the
ingest window: `LOOKBACK_DAYS=7` in `.env` cuts the paginated commits/PRs/issues
requests by roughly 4x, since only the busiest repositories need multiple pages
per 100 items. Lowering it also keeps `dbt_build` snappy.

The admin user/password comes from `_AIRFLOW_WWW_USER_USERNAME` /
`_AIRFLOW_WWW_USER_PASSWORD` in `.env`. The metadata database is a dedicated
`airflow` database inside the same Postgres (created by `airflow-db-create`).

### Changing dependencies

`docker/requirements.txt` is exported from `uv.lock`; regenerate it and
rebuild the image whenever `pyproject.toml` changes:

```bash
uv export --frozen --no-dev --no-emit-project --no-hashes \
    --output-file docker/requirements.txt
docker compose build
```

## dbt

The dbt project turns the raw tables into a documented star schema
(dimensions + facts) plus reporting aggregates. See
`dbt/github_analytics/README.md` for the lineage diagram and the grain of
every model.

```bash
cd dbt/github_analytics

# use the in-repo profile (reads the same env vars as the pipeline)
set -a && source ../../.env && set +a

uv run dbt build --profiles-dir .          # models + all tests
uv run dbt source freshness --profiles-dir .
uv run dbt docs generate --profiles-dir .  # then: dbt docs serve
```

Layers: `staging` (views, 1:1 with raw) → `intermediate` (reusable joins) →
`marts` (dims/facts, incremental) → `marts/reporting` (dashboards).

## Quality

```bash
uv run ruff check .
uv run pytest
```
