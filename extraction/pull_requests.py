import logging

import requests

from extraction.github_client import parse_github_time

logger = logging.getLogger(__name__)


def get_pull_requests(client, owner, repo, since=None, until=None):
    endpoint = f"/repos/{owner}/{repo}/pulls"
    params = {
        "state": "all",
        "sort": "updated",
        "direction": "desc",
    }

    try:
        for pr in client.get_with_pagination(endpoint, params):
            updated_at = parse_github_time(pr.get("updated_at"))

            if since and updated_at and updated_at < since:
                break

            if until and updated_at and updated_at > until:
                continue

            yield {
                "id": pr.get("id"),
                "number": pr.get("number"),
                "title": pr.get("title"),
                "user_login": (pr.get("user") or {}).get("login"),
                "state": pr.get("state"),
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "closed_at": pr.get("closed_at"),
                "merged_at": pr.get("merged_at"),
                "draft": pr.get("draft"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
            }

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning(
                "Pull requests endpoint returned 404 for %s/%s; skipping",
                owner,
                repo,
            )
            return

        raise
