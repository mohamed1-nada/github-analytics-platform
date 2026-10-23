#!/usr/bin/env python
"""Provision the Superset instance for the GitHub analytics warehouse.

Run by the ``superset-bootstrap`` service (see ``docker-compose.superset.yml``)
and safe to run repeatedly — everything it creates is looked up first and only
created when missing:

1. the read-only connection to the analytics database;
2. one physical dataset per dbt mart, so the dashboards have something to
   point at;
3. the dashboard definitions committed under ``superset/dashboards``;
4. the alert and the scheduled report that go with them.

The dashboard import is delegated to ``superset import-dashboards``, the
officially supported path: it remaps dataset references by name and writes
the dashboards into the metadata database.

Credentials come from the environment:

    SUPERSET_URL             base URL of the running webserver (default
                             http://localhost:8088)
    SUPERSET_ADMIN_USERNAME  admin account to authenticate with
    SUPERSET_ADMIN_PASSWORD
    ANALYTICS_DB_HOST/PORT/NAME/USER/PASSWORD  the warehouse connection
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://localhost:8088").rstrip("/")
ADMIN_USERNAME = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")

DB_HOST = os.environ.get("ANALYTICS_DB_HOST", "postgres")
DB_PORT = os.environ.get("ANALYTICS_DB_PORT", "5432")
DB_NAME = os.environ.get("ANALYTICS_DB_NAME", "github_analytics")
DB_USER = os.environ.get("ANALYTICS_DB_USER", "superset_ro")
DB_PASSWORD = os.environ.get("ANALYTICS_DB_PASSWORD", "superset_ro")

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboards"
SCHEMA = "public"
DATABASE_NAME = "GitHub Analytics"

# The dbt marts the dashboards are built on. Keeping the list explicit makes
# a missing mart a hard error instead of a silently absent dataset.
DATASETS = [
    "dim_repositories",
    "dim_contributors",
    "agg_repository_metrics",
    "agg_pull_request_summary",
    "agg_contributor_concentration",
    "agg_activity_trend",
    "agg_issue_backlog",
    "agg_repo_health",
    "fct_commits_daily",
    "fct_pull_requests",
    "fct_issues",
    "fct_commit_activity_weekly",
]


class SupersetApiError(RuntimeError):
    """Raised when the Superset API answers with an error status."""


def log(message: str) -> None:
    print(f"[bootstrap] {message}", flush=True)


# Superset requires a CSRF token on every state-changing request. The token
# is fetched once after login and sent back in the `X-CSRFToken` header --
# but the matching cookie has to travel with it, so every call goes through
# one persistent session.
SESSION = requests.Session()
CSRF_TOKEN: str | None = None


def request(method: str, path: str, token: str | None = None, **kwargs) -> dict | list:
    """Call the Superset REST API, raising on a non-2xx answer."""
    url = f"{SUPERSET_URL}{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if method.upper() != "GET" and CSRF_TOKEN:
        headers["X-CSRFToken"] = CSRF_TOKEN
        headers["Referer"] = SUPERSET_URL

    response = SESSION.request(method, url, headers=headers, timeout=60, **kwargs)

    if not response.ok:
        raise SupersetApiError(
            f"{method} {path} failed with {response.status_code}: {response.text[:500]}"
        )

    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def wait_for_superset(timeout: int = 300) -> None:
    """Block until the webserver answers its health check."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{SUPERSET_URL}/health", timeout=5)
            if response.ok:
                log("Superset webserver is healthy")
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    raise SupersetApiError(f"Superset did not become healthy within {timeout}s")


def login() -> tuple[str, int]:
    """Authenticate as the admin user, returning an access token and user id."""
    global CSRF_TOKEN

    payload = {
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
        "provider": "db",
        "refresh": True,
    }
    response = SESSION.post(f"{SUPERSET_URL}/api/v1/security/login", json=payload, timeout=60)
    if not response.ok:
        raise SupersetApiError(f"Login failed with {response.status_code}: {response.text[:500]}")
    token = response.json()["access_token"]

    # The CSRF token is required on every POST/PUT below.
    csrf = request("GET", "/api/v1/security/csrf_token/", token=token)
    CSRF_TOKEN = csrf.get("result") if isinstance(csrf, dict) else None
    if not CSRF_TOKEN:
        raise SupersetApiError("Could not obtain a CSRF token")

    me = request("GET", "/api/v1/me/", token=token)
    user_id = me.get("result", {}).get("id")
    if user_id is None:
        raise SupersetApiError("Could not resolve the admin user id")
    log(f"Authenticated as {ADMIN_USERNAME} (id {user_id})")
    return token, user_id


def ensure_database(token: str) -> int:
    """Create (or update) the read-only connection to the analytics database."""
    uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    body = {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": uri,
        "expose_in_sqllab": True,
        # The warehouse is owned by the dbt project: never let the UI write.
        "allow_ctas": False,
        "allow_cvas": False,
        "allow_dml": False,
        "allow_run_async": True,
        "cache_timeout": None,
        "extra": json.dumps(
            {
                "metadata_params": {},
                "engine_params": {"pool_pre_ping": True},
                "metadata_cache_timeout": {
                    "schema_cache_timeout": 600,
                    "table_cache_timeout": 600,
                },
                "schemas_allowed_for_file_upload": [],
            }
        ),
    }

    existing = request(
        "GET",
        "/api/v1/database/",
        token=token,
        params={
            "q": json.dumps(
                {"filters": [{"col": "database_name", "opr": "eq", "value": DATABASE_NAME}]}
            )
        },
    )
    results = existing.get("result", []) if isinstance(existing, dict) else []

    if results:
        database_id = results[0]["id"]
        body["id"] = database_id
        request("PUT", f"/api/v1/database/{database_id}", token=token, json=body)
        log(f"Updated database connection {DATABASE_NAME!r} (id {database_id})")
    else:
        created = request("POST", "/api/v1/database/", token=token, json=body)
        database_id = created["id"]
        log(f"Created database connection {DATABASE_NAME!r} (id {database_id})")

    return database_id


def ensure_datasets(token: str, database_id: int, owner_id: int) -> None:
    """Create a physical dataset for every mart, if it does not exist yet."""
    listing = request("GET", "/api/v1/dataset/", token=token, params={"page_size": 1000})
    existing = listing.get("result", []) if isinstance(listing, dict) else []
    known = {
        (item["database"]["id"], item["schema"], item["table_name"]): item for item in existing
    }

    created, skipped = 0, 0
    for table_name in DATASETS:
        key = (database_id, SCHEMA, table_name)
        if key in known:
            skipped += 1
            continue
        body = {
            "database": database_id,
            "schema": SCHEMA,
            "table_name": table_name,
            "owners": [owner_id],
        }
        request("POST", "/api/v1/dataset/", token=token, json=body)
        created += 1

    log(f"Datasets ready ({created} created, {skipped} already present)")


def import_dashboards() -> None:
    """Import the dashboard definitions committed under ``superset/dashboards``."""
    if not DASHBOARD_DIR.is_dir():
        log(f"No dashboard directory at {DASHBOARD_DIR}, skipping import")
        return

    archives = sorted(DASHBOARD_DIR.glob("*.zip"))
    if not archives:
        log(f"No dashboard archives in {DASHBOARD_DIR}, skipping import")
        return

    for archive in archives:
        log(f"Importing {archive.name}")
        # Superset 6.1's CLI always imports with overwrite=True and requires
        # an owner username; there is no --overwrite flag any more.
        result = subprocess.run(
            [
                "superset",
                "import-dashboards",
                "--path",
                str(archive),
                "--username",
                ADMIN_USERNAME,
            ],
            capture_output=True,
            text=True,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            log(f"Import of {archive.name} failed:\n{output.strip()}")
            raise SystemExit(result.returncode)
        log(f"Imported {archive.name}")


def ensure_reports() -> None:
    """Create the alert and the scheduled report (idempotent)."""
    # Imported here rather than at module scope: the script is a standalone
    # entry point too, and it needs the webserver to be up before it runs.
    from create_reports import main as create_reports_main

    log("Creating alerts and scheduled reports")
    if create_reports_main() != 0:
        raise SystemExit("Could not create the alerts and scheduled reports")


def main() -> int:
    wait_for_superset()
    token, user_id = login()
    database_id = ensure_database(token)
    ensure_datasets(token, database_id, user_id)
    import_dashboards()
    ensure_reports()
    log("Bootstrap complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SupersetApiError as error:
        log(f"ERROR: {error}")
        sys.exit(1)
