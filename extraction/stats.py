import logging

import requests

logger = logging.getLogger(__name__)


def get_commit_activity(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/commit_activity"

    try:
        data = client.get(endpoint)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("Commit activity stats not available for %s/%s (404)", owner, repo)
            return
        raise

    for week in data:
        days = week.get("days") or []
        if len(days) < 7:
            logger.warning("Skipping malformed commit-activity week for %s/%s", owner, repo)
            continue

        yield {
            "week": week.get("week"),
            "total_commits": week.get("total"),
            "sunday_commits": days[0],
            "monday_commits": days[1],
            "tuesday_commits": days[2],
            "wednesday_commits": days[3],
            "thursday_commits": days[4],
            "friday_commits": days[5],
            "saturday_commits": days[6],
        }


def get_contributors_stats(client, owner, repo):
    endpoint = f"/repos/{owner}/{repo}/stats/contributors"

    try:
        data = client.get(endpoint)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("Contributors stats not available for %s/%s (404)", owner, repo)
            return
        raise

    for contributor in data:
        author_info = contributor.get("author") or {}
        author_login = author_info.get("login")
        # skip None and deleted accounts
        if not author_login:
            continue
        yield {
            "author_login": author_login,
            "total_commits": contributor.get("total"),
        }
