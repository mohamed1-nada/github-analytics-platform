import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from config import get_settings
from extraction.github_client import GithubClient
from logging_config import setup_logging
from pipeline import run_pipeline
from repos import check_token, resolve_repos

logger = logging.getLogger(__name__)

ALL_STEPS = ["commits", "pull_requests", "issues", "commit_activity", "contributors"]


def parse_args():
    parser = argparse.ArgumentParser(description="GitHub analytics ingestion pipeline")
    parser.add_argument(
        "--repo",
        action="append",
        metavar="OWNER/NAME",
        help="Repository to ingest (repeatable). Overrides --repos-file.",
    )
    parser.add_argument(
        "--repos-file",
        default="repos.yaml",
        metavar="PATH",
        help="YAML file with a repos list and topics to discover (default: repos.yaml)",
    )
    parser.add_argument(
        "--no-topics",
        action="store_true",
        help="Skip topic discovery, use only the direct repos from the repos file",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print the resolved repository list and exit without ingesting",
    )
    parser.add_argument("--since", type=str, default=None, help="ISO start datetime")
    parser.add_argument("--until", type=str, default=None, help="ISO end datetime")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--step",
        action="append",
        choices=ALL_STEPS,
        default=None,
        help="Run only this step (repeatable). Defaults to all steps.",
    )
    return parser.parse_args()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def collect_repos(args) -> list[tuple[str, str]]:
    return resolve_repos(
        repos_file=Path(args.repos_file),
        explicit=args.repo,
        include_topics=not args.no_topics,
    )


def main():
    setup_logging()
    args = parse_args()
    settings = get_settings()

    since = parse_iso(args.since) or settings.default_since()
    until = parse_iso(args.until) or settings.default_until()
    if since >= until:
        raise SystemExit(f"--since ({since}) must be before --until ({until})")
    batch_size = args.batch_size or settings.batch_size

    repos = collect_repos(args)
    if not repos:
        raise SystemExit("No repositories to ingest (check --repo / repos.yaml)")

    if args.list_only:
        for owner, name in repos:
            print(f"{owner}/{name}")
        print(f"\n{len(repos)} repositories")
        return

    # Fail fast with an actionable message instead of letting the first
    # repository extraction die on a 401 halfway through the run.
    check_token(GithubClient())

    logger.info("Ingesting %d repositories from %s to %s", len(repos), since, until)

    failed = []
    for owner, repo_name in repos:
        results = run_pipeline(owner, repo_name, batch_size, since, until, only_steps=args.step)
        if not results or "Failed" in results.values():
            failed.append(f"{owner}/{repo_name}")

    if failed:
        logger.error(
            "Pipeline finished with failures in %d/%d repos: %s",
            len(failed),
            len(repos),
            ", ".join(failed),
        )
        sys.exit(1)

    logger.info("Pipeline finished successfully for all %d repositories", len(repos))


if __name__ == "__main__":
    main()
