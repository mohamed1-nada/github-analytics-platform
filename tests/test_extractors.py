from datetime import UTC, datetime

import pytest
import requests

from extraction.commits import get_commits
from extraction.issues import get_issues
from extraction.pull_requests import get_pull_requests


class FakeClient:
    """Records the params it was called with and replays canned pages."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_with_pagination(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        yield from self.pages


def error_response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class FailingClient:
    """A client whose pagination fails, either on call or on first iteration.

    ``lazy=True`` mirrors ``GithubClient.get_with_pagination``: the method is a
    generator, so the HTTPError only appears while iterating. That is the case
    the extractors originally mishandled.
    """

    def __init__(self, status_code: int, lazy: bool = True):
        self.status_code = status_code
        self.lazy = lazy

    def get_with_pagination(self, endpoint, params=None):
        if self.lazy:
            if False:  # pragma: no cover - makes this a generator function
                yield {}
            raise requests.exceptions.HTTPError(response=error_response(self.status_code))
        raise requests.exceptions.HTTPError(response=error_response(self.status_code))


def test_get_issues_filters_pull_requests():
    client = FakeClient(
        [
            {
                "id": 1,
                "number": 1,
                "title": "bug",
                "user": {"login": "alice"},
                "state": "open",
                "comments": 0,
            },
            {"id": 2, "number": 2, "title": "pr", "pull_request": {}, "user": {"login": "bob"}},
        ]
    )

    issues = list(get_issues(client, "o", "r"))

    assert len(issues) == 1
    assert issues[0]["user_login"] == "alice"


def test_get_issues_requests_all_states():
    client = FakeClient([])
    list(get_issues(client, "o", "r"))

    _, params = client.calls[0]
    assert params["state"] == "all"


def test_get_issues_applies_until_client_side():
    client = FakeClient(
        [
            {"id": 1, "number": 1, "title": "after window", "updated_at": "2025-09-10T00:00:00Z"},
            {"id": 2, "number": 2, "title": "in window", "updated_at": "2025-08-01T00:00:00Z"},
        ]
    )

    issues = list(get_issues(client, "o", "r", until=datetime(2025, 9, 1, tzinfo=UTC)))

    assert [i["id"] for i in issues] == [2]


def test_get_pull_requests_stops_at_since():
    client = FakeClient(
        [
            {"id": 1, "number": 1, "updated_at": "2025-09-10T00:00:00Z"},
            {"id": 2, "number": 2, "updated_at": "2025-08-01T00:00:00Z"},
            {"id": 3, "number": 3, "updated_at": "2025-07-01T00:00:00Z"},
        ]
    )

    prs = list(get_pull_requests(client, "o", "r", since=datetime(2025, 9, 1, tzinfo=UTC)))

    assert [p["id"] for p in prs] == [1]


def test_get_pull_requests_sorts_by_updated_desc():
    client = FakeClient([])
    list(get_pull_requests(client, "o", "r"))

    _, params = client.calls[0]
    assert params["sort"] == "updated"
    assert params["direction"] == "desc"
    assert params["state"] == "all"


def test_get_pull_requests_without_since_yields_all():
    client = FakeClient(
        [
            {"id": 1, "updated_at": "2020-01-01T00:00:00Z"},
            {"id": 2, "updated_at": "2010-01-01T00:00:00Z"},
        ]
    )

    prs = list(get_pull_requests(client, "o", "r", since=None))

    assert [p["id"] for p in prs] == [1, 2]


# --- 404 handling ---------------------------------------------------------
# The pagination helper is a generator: the request happens on iteration.
# These tests reproduce that shape so the fallback stays reachable.


@pytest.mark.parametrize("lazy", [True, False])
def test_get_commits_swallows_404(lazy):
    assert list(get_commits(FailingClient(404, lazy=lazy), "o", "r")) == []


@pytest.mark.parametrize("lazy", [True, False])
def test_get_issues_swallows_404(lazy):
    assert list(get_issues(FailingClient(404, lazy=lazy), "o", "r")) == []


@pytest.mark.parametrize("lazy", [True, False])
def test_get_commits_reraises_other_errors(lazy):
    with pytest.raises(requests.exceptions.HTTPError):
        list(get_commits(FailingClient(500, lazy=lazy), "o", "r"))


@pytest.mark.parametrize("lazy", [True, False])
def test_get_issues_reraises_other_errors(lazy):
    with pytest.raises(requests.exceptions.HTTPError):
        list(get_issues(FailingClient(500, lazy=lazy), "o", "r"))
