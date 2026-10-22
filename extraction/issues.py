import logging

import requests

from extraction.github_client import parse_github_time, to_github_time

logger = logging.getLogger(__name__)


def get_issues(client, owner, repo, since=None, until=None):
    """Yield issues (pull requests excluded) updated inside [since, until]."""
    endpoint = f"/repos/{owner}/{repo}/issues"
    params = {"state": "all"}
    if since:
        params["since"] = to_github_time(since)

    # See get_commits: the pagination helper only performs the request while
    # iterating, so the loop must be inside the try for the 404 fallback to
    # ever run.
    try:
        for issue in client.get_with_pagination(endpoint, params):
            if "pull_request" in issue:
                continue
            if until:
                updated_at = parse_github_time(issue.get("updated_at"))
                if updated_at and updated_at > until:
                    continue
            yield {
                "id": issue.get("id"),
                "number": issue.get("number"),
                "title": issue.get("title"),
                "user_login": (issue.get("user") or {}).get("login"),
                "state": issue.get("state"),
                "comments": issue.get("comments"),
                "created_at": issue.get("created_at"),
                "updated_at": issue.get("updated_at"),
                "closed_at": issue.get("closed_at"),
            }
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("Issues endpoint not available for %s/%s (404)", owner, repo)
            return
        raise
