"""GitHub analytics pipeline: ingest raw data into Postgres, then run dbt.

Ingestion is mapped one task per repository (resolved from repos.yaml at run
time), so a single failing repository retries on its own without re-running
the others. The dbt build runs once after all repositories finish.

Scheduled runs ingest the previous data interval (daily window); manual runs
without a meaningful interval fall back to the configured LOOKBACK_DAYS
window. The loaders are upserts, so re-runs and backfills are idempotent.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from airflow.exceptions import AirflowException
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task
from airflow.utils.trigger_rule import TriggerRule
from pendulum import datetime

from config import get_settings
from database.init.create_tables import create_tables
from pipeline import run_pipeline
from repos import resolve_repos

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = PROJECT_ROOT / "dbt" / "github_analytics"


@task(execution_timeout=timedelta(minutes=5))
def init_tables() -> None:
    """Create the raw tables if they don't exist (idempotent DDL)."""
    create_tables()


@task
def list_repos(**context) -> list[str]:
    """Resolve the repository list at run time (repos.yaml + topic discovery).

    A manual run may override the configured list with
    ``{"repos": ["OWNER/NAME", ...]}`` in the DAG run conf; this is handy for
    smoke tests and for backfilling a single repository.
    """
    override = (context.get("dag_run") and context["dag_run"].conf or {}).get("repos")
    if override:
        resolved = resolve_repos(explicit=list(override))
    else:
        resolved = resolve_repos(repos_file=PROJECT_ROOT / "repos.yaml")
    logger.info("Resolved %d repositories to ingest", len(resolved))
    return [f"{owner}/{name}" for owner, name in resolved]


@task(execution_timeout=timedelta(minutes=90))
def ingest_repo(repo: str, **context) -> dict[str, str]:
    """Run the full extract/load pipeline for one repository.

    The data interval is read from ``**context`` (with a lookback fallback)
    rather than declared as named parameters: TaskFlow only injects context
    keys that are present in the execution context, and named parameters that
    go unfilled make the task fail with a TypeError on some run types.
    """
    settings = get_settings()
    data_interval_start = context.get("data_interval_start")
    data_interval_end = context.get("data_interval_end")

    # Scheduled runs ingest the data interval; manual runs with an empty
    # interval (start >= end) fall back to the configured lookback window.
    if data_interval_start is not None and data_interval_start < (
        data_interval_end or data_interval_start
    ):
        since, until = data_interval_start, data_interval_end
    else:
        since, until = settings.default_since(), settings.default_until()

    owner, _, name = repo.partition("/")
    logger.info("Ingesting %s from %s to %s", repo, since, until)

    results = run_pipeline(owner, name, settings.batch_size, since, until)

    failed = [step for step, status in results.items() if status != "Success"]
    if not results:
        raise AirflowException(f"{repo}: repository extraction failed (no results)")
    if failed:
        raise AirflowException(f"{repo}: failed steps: {', '.join(failed)}")
    return results


@dag(
    dag_id="github_analytics",
    description="Ingest GitHub repository data into Postgres and transform it with dbt",
    schedule="0 4 * * *",
    start_date=datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_tasks=4,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
    },
    tags=["github", "ingestion", "dbt"],
)
def github_analytics():
    tables = init_tables()
    repos = list_repos()
    tables >> repos

    ingested = ingest_repo.expand(repo=repos)

    # `ALL_DONE` (not the default `all_success`): ingestion is idempotent
    # upserts, so a partial load still produces a valid — if incomplete —
    # warehouse. With the default rule a single failing repository skipped
    # the dbt build entirely and left the mart stale for days, which is what
    # silently dropped the vast majority of the facts.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command="dbt build --profiles-dir .",
        cwd=str(DBT_DIR),
        execution_timeout=timedelta(minutes=30),
        trigger_rule=TriggerRule.ALL_DONE,
    )
    ingested >> dbt_build


# Instantiate at module level so the DAG is registered when this file is parsed.
github_analytics_dag = github_analytics()
