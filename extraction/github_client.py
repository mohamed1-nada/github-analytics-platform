import logging
import time
from datetime import UTC, datetime

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config import get_settings

logger = logging.getLogger(__name__)


def to_github_time(value: datetime | None) -> str | None:
    """Format a datetime the way GitHub expects: ISO8601 in UTC, e.g. 2025-09-01T00:00:00Z."""
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_github_time(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp (e.g. 2025-09-01T00:00:00Z) into an aware datetime."""
    return datetime.fromisoformat(value) if value else None


def is_transient_error(exception: BaseException) -> bool:
    """Whether a failed request is worth retrying.

    GitHub's statistics endpoints (``/stats/contributors``,
    ``/stats/commit_activity``) are computed on demand and regularly answer
    with a 5xx while they do so. Those failures are transient, so the request
    is worth repeating; a 404 or a 422 is not.

    A 429 is included as well: the rate-limit handler normally sleeps until
    the window resets, but if the response carries no usable timing headers
    a short retry still beats failing the step outright.
    """
    if isinstance(exception, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    if isinstance(exception, requests.exceptions.HTTPError):
        response = exception.response
        return response is not None and response.status_code in {429, 500, 502, 503, 504}
    return False


def rate_limit_delay(response: requests.Response) -> float | None:
    """Return how many seconds to wait if ``response`` is a rate-limit rejection.

    GitHub uses two flavours of limit:

    * the primary limit, which answers 403/429 once the quota is drained and
      carries ``X-RateLimit-Remaining: 0`` plus an epoch ``X-RateLimit-Reset``;
    * the secondary (and per-endpoint, e.g. search) limit, which usually
      carries ``Retry-After`` and does not necessarily drain the quota.

    ``None`` means "not a rate-limit response", so the caller can surface the
    error normally (a plain 403 is a permission problem, not a quota one).
    """
    if response.status_code not in (403, 429):
        return None

    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            return 60.0

    remaining = response.headers.get("X-RateLimit-Remaining")
    reset = response.headers.get("X-RateLimit-Reset")
    if remaining == "0" and reset:
        try:
            return max(int(reset) - int(time.time()), 1) + 1
        except ValueError:
            return 60.0

    # A 429 is always a rate-limit answer, even without timing headers.
    if response.status_code == 429:
        return 60.0

    # Secondary limits do not always send Retry-After or drain the quota, but
    # their body always says so. Guard the body read: a streaming response
    # raises when asked for .text.
    try:
        body = response.text.lower()
    except Exception:
        body = ""
    if "rate limit" in body:
        return 60.0

    return None


def _json(response: requests.Response):
    """Decode a response body, treating an empty body as an empty list."""
    if not response.content:
        return []
    return response.json()


class GithubClient:
    def __init__(self, token: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self.base_url = base_url or settings.base_url

        token = token or settings.github_token
        if not token:
            raise SystemExit(
                "GITHUB_TOKEN is not set. Add it to .env "
                "(create a token at https://github.com/settings/tokens)."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )

    def _wait_for_rate_limit(self, response: requests.Response) -> bool:
        """Sleep when ``response`` is a rate-limit rejection; report if it was."""
        delay = rate_limit_delay(response)
        if delay is None:
            return False

        logger.warning(
            "Rate limit hit (%s); sleeping %.0f seconds before retrying",
            response.status_code,
            delay,
        )
        time.sleep(delay)
        return True

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(is_transient_error),
        reraise=True,
    )
    def _get(self, endpoint, params=None) -> requests.Response:
        url = f"{self.base_url}{endpoint}"

        logger.info("GET %s", url)

        while True:
            response = self.session.get(
                url,
                params=params,
                timeout=(10, 30),
            )

            if self._wait_for_rate_limit(response):
                continue

            response.raise_for_status()

            logger.info("Response: %s", response.status_code)
            return response

    def get(self, endpoint, params=None, pending_retries: int = 3, pending_delay: float = 5.0):
        """GET an endpoint, retrying while GitHub computes statistics.

        The statistics endpoints answer ``202 Accepted`` with an empty body
        while the numbers are being calculated. Returning ``[]`` immediately
        used to drop that repository's stats for the day, so wait and ask
        again before giving up.
        """
        for attempt in range(pending_retries + 1):
            response = self._get(endpoint, params)

            if response.status_code != 202:
                return _json(response)

            if attempt == pending_retries:
                logger.warning(
                    "202 Accepted for %s after %d attempts — statistics are still "
                    "being computed, skipping this run",
                    endpoint,
                    pending_retries + 1,
                )
                return []

            logger.info(
                "202 Accepted for %s — statistics are being computed, retrying in %.0fs",
                endpoint,
                pending_delay,
            )
            time.sleep(pending_delay)

        return []

    def get_search_items(self, endpoint, params=None) -> list[dict]:
        """Search endpoints wrap their results in an ``items`` key instead of a bare list."""
        payload = self.get(endpoint, params)
        if not isinstance(payload, dict):
            return []
        return payload.get("items") or []

    def get_with_pagination(self, endpoint, params=None):
        params = params.copy() if params else {}

        params.setdefault("page", 1)
        params.setdefault("per_page", 100)

        max_pages = get_settings().max_pages

        while True:
            if params["page"] > max_pages:
                # A single bot-driven repository can commit hundreds of times a
                # day; without a guard one repo would paginate until it exhausts
                # the hourly API quota and never finish. Keep the newest pages.
                logger.warning(
                    "Stopping pagination for %s at the %d-page cap (~%d items); "
                    "narrow the window (--since) to load the rest.",
                    endpoint,
                    max_pages,
                    max_pages * params["per_page"],
                )
                break

            try:
                response = self._get(endpoint, params)
            except requests.exceptions.HTTPError as e:
                # GitHub refuses to paginate past 10,000 results for some list
                # endpoints (issues, pulls) with a 422. Keep what we have and
                # tell the caller to narrow the window.
                if e.response is not None and e.response.status_code == 422 and params["page"] > 1:
                    logger.warning(
                        "GitHub pagination cap reached for %s after ~%d items; "
                        "narrow the time window (--since) to load the rest.",
                        endpoint,
                        (params["page"] - 1) * params["per_page"],
                    )
                    break
                raise

            yield from _json(response)

            link_header = response.headers.get("Link", "")

            if 'rel="next"' not in link_header:
                break

            params["page"] += 1
