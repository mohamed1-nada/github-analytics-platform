import json

import pytest
import requests

from extraction.github_client import GithubClient


class _FakeResponse(requests.Response):
    def __init__(self, status_code: int, payload=None, headers=None):
        super().__init__()
        self.status_code = status_code
        self._payload = [] if payload is None else payload
        # requests' .content/.text read this attribute; fill it so the fake
        # behaves like a real consumed response.
        self._content = json.dumps(self._payload).encode()
        self.headers.update(headers or {})

    def json(self):
        return self._payload


def test_pagination_follows_next_link(monkeypatch):
    client = GithubClient(token="x")
    pages = [
        _FakeResponse(200, [{"id": 1}], {"Link": '<https://api.github.com/x?page=2>; rel="next"'}),
        _FakeResponse(200, [{"id": 2}], {}),
    ]
    monkeypatch.setattr(client, "_get", lambda endpoint, params: pages[params["page"] - 1])

    assert [row["id"] for row in client.get_with_pagination("/x")] == [1, 2]


def test_pagination_stops_at_github_cap(monkeypatch):
    client = GithubClient(token="x")
    cap_error = requests.exceptions.HTTPError(response=_FakeResponse(422))

    def fake_get(endpoint, params):
        if params["page"] == 1:
            return _FakeResponse(
                200, [{"id": 1}], {"Link": '<https://api.github.com/x?page=2>; rel="next"'}
            )
        raise cap_error

    monkeypatch.setattr(client, "_get", fake_get)

    # Partial data is returned instead of raising, so the step still loads.
    assert [row["id"] for row in client.get_with_pagination("/x")] == [1]


def test_pagination_reraises_422_on_first_page(monkeypatch):
    client = GithubClient(token="x")
    bad_request = requests.exceptions.HTTPError(response=_FakeResponse(422))
    monkeypatch.setattr(client, "_get", lambda endpoint, params: (_ for _ in ()).throw(bad_request))

    with pytest.raises(requests.exceptions.HTTPError):
        list(client.get_with_pagination("/x"))


def test_pagination_stops_at_page_cap(monkeypatch):
    client = GithubClient(token="x")
    requested_pages = []

    def fake_get(endpoint, params):
        requested_pages.append(params["page"])
        # Always advertise a next page: only the cap can stop this loop.
        return _FakeResponse(
            200,
            [{"id": params["page"]}],
            {"Link": f'<https://api.github.com/x?page={params["page"] + 1}>; rel="next"'},
        )

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(
        "extraction.github_client.get_settings",
        lambda: type("S", (), {"max_pages": 3})(),
    )

    rows = list(client.get_with_pagination("/x"))

    assert [row["id"] for row in rows] == [1, 2, 3]
    assert requested_pages == [1, 2, 3]


# --- Rate limiting --------------------------------------------------------


def _client(monkeypatch):
    slept = []
    monkeypatch.setattr("extraction.github_client.time.sleep", slept.append)
    return GithubClient(token="x"), slept


def test_rate_limit_uses_retry_after(monkeypatch):
    client, slept = _client(monkeypatch)
    response = _FakeResponse(403, headers={"Retry-After": "7", "X-RateLimit-Remaining": "42"})

    assert client._wait_for_rate_limit(response) is True
    assert slept == [7.0]


def test_rate_limit_uses_reset_when_quota_is_drained(monkeypatch):
    client, slept = _client(monkeypatch)
    monkeypatch.setattr("extraction.github_client.time.time", lambda: 1000)
    response = _FakeResponse(
        403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"}
    )

    assert client._wait_for_rate_limit(response) is True
    assert slept == [31.0]


def test_rate_limit_detects_secondary_limit_from_body(monkeypatch):
    client, slept = _client(monkeypatch)
    response = _FakeResponse(
        403,
        payload={"message": "You have exceeded a secondary rate limit."},
        headers={"X-RateLimit-Remaining": "4800"},
    )

    assert client._wait_for_rate_limit(response) is True
    assert slept == [60.0]


def test_plain_403_is_not_a_rate_limit(monkeypatch):
    client, slept = _client(monkeypatch)
    response = _FakeResponse(403, payload={"message": "Forbidden"})

    assert client._wait_for_rate_limit(response) is False
    assert slept == []


def test_429_without_timing_headers_still_waits(monkeypatch):
    client, slept = _client(monkeypatch)
    response = _FakeResponse(429, payload={"message": "Too Many Requests"})

    assert client._wait_for_rate_limit(response) is True
    assert slept == [60.0]


# --- 202 Accepted (statistics still computing) ----------------------------


def test_202_is_retried_until_data_is_ready(monkeypatch):
    client, slept = _client(monkeypatch)
    responses = [_FakeResponse(202), _FakeResponse(200, [{"id": 1}])]
    monkeypatch.setattr(client, "_get", lambda endpoint, params: responses.pop(0))

    assert client.get("/stats") == [{"id": 1}]
    assert len(slept) == 1


def test_202_gives_up_after_retries(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(client, "_get", lambda endpoint, params: _FakeResponse(202))

    assert client.get("/stats", pending_retries=2) == []
