"""Discover repositories to ingest from the GitHub Search API."""

import logging

logger = logging.getLogger(__name__)

# Keep discovered repos analyzable: popular, live, and not duplicated forks.
SEARCH_QUALIFIERS = "stars:>=1000 archived:false fork:false"


def discover_repos(client, topic: str, top: int = 10) -> list[tuple[str, str]]:
    """Return up to ``top`` (owner, name) pairs for ``topic``, most-starred first.

    The search endpoint returns at most 100 items per page, so ``top`` larger
    than 100 is served by following pagination until the limit is reached.
    """
    endpoint = "/search/repositories"
    base_params = {"sort": "stars", "order": "desc", "per_page": 100}

    repos: list[tuple[str, str]] = []
    for page in range(1, (top - 1) // 100 + 2):  # 1 .. ceil(top / 100)
        params = {**base_params, "q": f"topic:{topic} {SEARCH_QUALIFIERS}", "page": page}

        items = client.get_search_items(endpoint, params)
        if not items:
            break

        for repo in items:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            owner, _, name = full_name.partition("/")
            repos.append((owner, name))
            if len(repos) >= top:
                break

        if len(repos) >= top or len(items) < base_params["per_page"]:
            break

    logger.info("Discovered %d repositories for topic %r", len(repos), topic)
    return repos
