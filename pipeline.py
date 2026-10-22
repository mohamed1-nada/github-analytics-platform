import logging
from collections.abc import Callable, Iterable

from database.init.db import create_connection
from database.init.loader import (
    attach_repository_id,
    insert_commit_activity,
    insert_commits,
    insert_contributors,
    insert_issues,
    insert_pull_requests,
    insert_repositories,
    load_in_batches,
)
from extraction.commits import get_commits
from extraction.github_client import GithubClient
from extraction.issues import get_issues
from extraction.pull_requests import get_pull_requests
from extraction.repositories import get_repo
from extraction.stats import get_commit_activity, get_contributors_stats

logger = logging.getLogger(__name__)


def run_step(
    step_name: str,
    conn,
    extract_func: Callable[[], Iterable[dict]],
    load_func: Callable[[Iterable[dict]], int],
) -> str:
    """Run one pipeline step; on failure roll back and continue."""
    try:
        logger.info("Starting %s extraction", step_name)
        # ``extract_func`` returns a generator, so it is always truthy; the
        # number of loaded rows is what tells us whether there was any data.
        data = extract_func()

        logger.info("Starting %s loading", step_name)
        loaded = load_func(data)
        conn.commit()

        if loaded:
            logger.info("%s completed successfully (%d rows)", step_name, loaded)
        else:
            logger.info("No data to load for %s", step_name)
    except Exception as e:
        conn.rollback()
        logger.error("%s failed: %s", step_name, e, exc_info=True)
        return "Failed"

    return "Success"


def build_steps(client, owner, repo_name, since, until):
    """Return (name, extract, insert) triples for each raw table."""
    return [
        (
            "commits",
            lambda: get_commits(client, owner, repo_name, since=since, until=until),
            insert_commits,
        ),
        (
            "pull_requests",
            lambda: get_pull_requests(client, owner, repo_name, since=since, until=until),
            insert_pull_requests,
        ),
        (
            "issues",
            lambda: get_issues(client, owner, repo_name, since=since, until=until),
            insert_issues,
        ),
        (
            "commit_activity",
            lambda: get_commit_activity(client, owner, repo_name),
            insert_commit_activity,
        ),
        (
            "contributors",
            lambda: get_contributors_stats(client, owner, repo_name),
            insert_contributors,
        ),
    ]


def run_pipeline(owner, repo_name, batch_size, since, until, only_steps=None):
    logger.info("Starting pipeline for %s/%s from %s to %s", owner, repo_name, since, until)

    client = GithubClient()

    try:
        repo = get_repo(client, owner, repo_name)
        logger.info("Repository extracted successfully: %s", repo["full_name"])
    except Exception as e:
        logger.error("Repository extraction failed: %s", e, exc_info=True)
        return {}

    conn = create_connection()
    try:
        try:
            insert_repositories(conn, repo)
            conn.commit()
            logger.info("Repository loaded successfully: %s", repo["full_name"])
        except Exception as e:
            logger.error("Repository loading failed: %s", e, exc_info=True)
            conn.rollback()
            return {}

        results = {}
        for name, extract, insert in build_steps(client, owner, repo_name, since, until):
            if only_steps and name not in only_steps:
                continue
            results[name] = run_step(
                name,
                conn,
                extract,
                lambda data, insert=insert: load_in_batches(
                    attach_repository_id(data, repo["id"]),
                    batch_size,
                    lambda batch: insert(conn, batch),
                ),
            )

        logger.info("=" * 50)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 50)
        for step, status in results.items():
            logger.info("%20s %s", step, status)
        logger.info("=" * 50)
        return results
    except Exception as e:
        conn.rollback()
        logger.error("Unexpected pipeline error: %s", e, exc_info=True)
        return {}
    finally:
        conn.close()
        logger.info("Database connection closed")
