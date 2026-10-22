"""Repository list resolution, shared by the CLI (main.py) and the Airflow DAG."""

import logging
from pathlib import Path

import requests
import yaml

from config import DEFAULT_REPOS
from extraction.discovery import discover_repos
from extraction.github_client import GithubClient

logger = logging.getLogger(__name__)

DEFAULT_TOP = 10


def parse_repo(value: str) -> tuple[str, str]:
    owner, _, name = value.partition("/")
    if not owner or not name:
        raise SystemExit(f"Repository must be OWNER/NAME, got {value!r}")
    return owner, name


def load_repos_file(path: Path) -> tuple[list[tuple[str, str]], list[tuple[str, int]]]:
    """Read a repos file -> (direct repos, topic discovery requests as (topic, top))."""
    if not path.exists():
        logger.warning("Repos file %s not found, falling back to defaults", path)
        return [], []

    data = yaml.safe_load(path.read_text()) or {}

    direct = [parse_repo(r) for r in data.get("repos") or []]

    topics = []
    for entry in data.get("topics") or []:
        if isinstance(entry, str):
            topics.append((entry, DEFAULT_TOP))
        else:
            topics.append((entry["name"], int(entry.get("top", DEFAULT_TOP))))

    return direct, topics


def dedupe(repos: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique = []
    for repo in repos:
        if repo not in seen:
            seen.add(repo)
            unique.append(repo)
    return unique


def check_token(client) -> None:
    """Fail fast with a clear message when the configured token is invalid."""
    try:
        client.get("/user")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            raise SystemExit(
                "GITHUB_TOKEN in .env is invalid or expired. "
                "Create a new token at https://github.com/settings/tokens"
            ) from None
        raise


def resolve_repos(
    repos_file: Path | str = "repos.yaml",
    explicit: list[str] | None = None,
    include_topics: bool = True,
) -> list[tuple[str, str]]:
    """Resolve the repository list.

    ``explicit`` (ad-hoc ``--repo`` values) wins over the repos file. Topic
    discovery talks to the GitHub Search API, so it must run at task runtime,
    never at DAG parse time.
    """
    if explicit:
        return dedupe([parse_repo(r) for r in explicit])

    direct, topics = load_repos_file(Path(repos_file))

    repos = list(direct)

    if topics and include_topics:
        client = GithubClient()
        check_token(client)
        for topic, top in topics:
            repos.extend(discover_repos(client, topic, top))

    if not repos:
        logger.warning("No repositories configured, using built-in defaults")
        repos = list(DEFAULT_REPOS)

    return dedupe(repos)
