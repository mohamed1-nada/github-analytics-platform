import logging

import requests

from extraction.github_client import to_github_time

logger = logging.getLogger(__name__)


def get_commits(client, owner, repo, since=None, until=None):
    endpoint = f"/repos/{owner}/{repo}/commits"
    params = {}
    if since:
        params["since"] = to_github_time(since)
    if until:
        params["until"] = to_github_time(until)

    # The pagination helper is a generator: the request (and therefore any
    # HTTPError) only happens while iterating, so the loop has to live inside
    # the try block. Wrapping only the call made the 404 fallback dead code.
    try:
        for commit in client.get_with_pagination(endpoint, params):
            commit_data = commit.get("commit") or {}
            author_data = commit_data.get("author") or {}
            committer_data = commit_data.get("committer") or {}

            yield {
                "sha": commit.get("sha"),
                "author_login": (commit.get("author") or {}).get("login"),
                "author_name": author_data.get("name"),
                "committer_login": (commit.get("committer") or {}).get("login"),
                "commit_author_date": author_data.get("date"),
                "commit_committer_date": committer_data.get("date"),
                "commit_message": commit_data.get("message"),
            }
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("Commits endpoint not available for %s/%s (404)", owner, repo)
            return
        raise
