#!/usr/bin/env python
"""Small client for the Superset REST API.

Wraps the two things that make the API awkward to call from a script:

* the **session** — Superset protects state-changing calls with Flask-WTF's
  CSRF check, which needs both the ``X-CSRFToken`` header *and* the cookie
  that goes with it, so every call has to travel over the same session;
* the **JWT** — the access token goes in the ``Authorization`` header.

Everything else is a thin wrapper over the documented endpoints. The client
is deliberately read/write symmetric: ``create_*`` helpers look the object up
first and only create it when it is missing, so a script can be re-run
without duplicating anything.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

DEFAULT_URL = os.environ.get("SUPERSET_URL", "http://localhost:8088").rstrip("/")
DEFAULT_USERNAME = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
DEFAULT_PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")


class SupersetError(RuntimeError):
    """Raised when the Superset API answers with an error status."""


class SupersetClient:
    """A thin, session-aware wrapper around the Superset REST API."""

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.token: str | None = None
        self.csrf_token: str | None = None
        self.user_id: int | None = None

    # --- plumbing ---------------------------------------------------------

    def request(self, method: str, path: str, *, expect_json: bool = True, **kwargs) -> Any:
        """Call the API, raising :class:`SupersetError` on a non-2xx answer."""
        url = f"{self.base_url}{path}"
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if method.upper() != "GET" and self.csrf_token:
            headers["X-CSRFToken"] = self.csrf_token
            headers["Referer"] = self.base_url

        response = self.session.request(method, url, headers=headers, timeout=120, **kwargs)
        if not response.ok:
            raise SupersetError(f"{method} {path} -> {response.status_code}: {response.text[:800]}")
        if not expect_json or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    def wait_until_healthy(self, timeout: int = 300) -> None:
        """Block until the webserver answers its health check."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = self.session.get(f"{self.base_url}/health", timeout=5)
                if response.ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(3)
        raise SupersetError(f"Superset did not become healthy within {timeout}s")

    def login(self) -> SupersetClient:
        """Authenticate and fetch the CSRF token."""
        response = self.session.post(
            f"{self.base_url}/api/v1/security/login",
            json={
                "username": self.username,
                "password": self.password,
                "provider": "db",
                "refresh": True,
            },
            timeout=60,
        )
        if not response.ok:
            raise SupersetError(f"Login failed with {response.status_code}: {response.text[:500]}")
        self.token = response.json()["access_token"]

        csrf = self.request("GET", "/api/v1/security/csrf_token/")
        self.csrf_token = csrf.get("result") if isinstance(csrf, dict) else None
        if not self.csrf_token:
            raise SupersetError("Could not obtain a CSRF token")

        me = self.request("GET", "/api/v1/me/")
        self.user_id = me.get("result", {}).get("id")
        return self

    # --- lookups ----------------------------------------------------------

    def databases(self) -> list[dict]:
        return self.request("GET", "/api/v1/database/?page_size=100").get("result", [])

    def database_by_name(self, name: str) -> dict | None:
        for database in self.databases():
            if database.get("database_name") == name:
                return database
        return None

    def datasets(self) -> list[dict]:
        return self.request("GET", "/api/v1/dataset/?page_size=1000").get("result", [])

    def dataset_by_table(self, table_name: str) -> dict | None:
        for dataset in self.datasets():
            if dataset.get("table_name") == table_name:
                return dataset
        return None

    def dataset(self, dataset_id: int) -> dict:
        """The full dataset, including its columns and metrics."""
        return self.request("GET", f"/api/v1/dataset/{dataset_id}").get("result", {})

    def update_dataset(self, dataset_id: int, **fields) -> None:
        """Update a dataset (columns, metrics, main date column, ...)."""
        self.request("PUT", f"/api/v1/dataset/{dataset_id}", json=dict(fields))

    def refresh_dataset(self, dataset_id: int) -> None:
        """Re-introspect the underlying table so new columns are picked up."""
        self.request("PUT", f"/api/v1/dataset/{dataset_id}/refresh")

    def charts(self) -> list[dict]:
        return self.request("GET", "/api/v1/chart/?page_size=1000").get("result", [])

    def dashboards(self) -> list[dict]:
        return self.request("GET", "/api/v1/dashboard/?page_size=1000").get("result", [])

    # --- charts -----------------------------------------------------------

    def create_chart(
        self,
        *,
        dataset_id: int,
        slice_name: str,
        viz_type: str,
        params: dict,
        query_context: dict,
        description: str | None = None,
        owners: list[int] | None = None,
    ) -> int:
        """Create a chart and return its id."""
        body: dict[str, Any] = {
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "slice_name": slice_name,
            "viz_type": viz_type,
            "params": json.dumps(params),
            "query_context": json.dumps(query_context),
            "cache_timeout": None,
        }
        if description:
            body["description"] = description
        if owners or self.user_id:
            body["owners"] = owners or [self.user_id]

        created = self.request("POST", "/api/v1/chart/", json=body)
        return created["id"]

    def update_chart(self, chart_id: int, **fields) -> None:
        body = {
            key: (json.dumps(value) if isinstance(value, (dict, list)) else value)
            for key, value in fields.items()
        }
        self.request("PUT", f"/api/v1/chart/{chart_id}", json=body)

    def delete_chart(self, chart_id: int) -> None:
        self.request("DELETE", f"/api/v1/chart/{chart_id}")

    # --- dashboards -------------------------------------------------------

    def create_dashboard(
        self,
        *,
        dashboard_title: str,
        slug: str,
        position: dict,
        json_metadata: dict,
        owners: list[int] | None = None,
    ) -> int:
        """Create a dashboard and return its id."""
        body: dict[str, Any] = {
            "dashboard_title": dashboard_title,
            "slug": slug,
            # Superset 6 renamed the layout field to `position_json`.
            "position_json": json.dumps(position),
            "json_metadata": json.dumps(json_metadata),
            "published": True,
        }
        if owners or self.user_id:
            body["owners"] = owners or [self.user_id]

        created = self.request("POST", "/api/v1/dashboard/", json=body)
        return created["id"]

    def update_dashboard(self, dashboard_id: int, **fields) -> None:
        body = {
            key: (json.dumps(value) if isinstance(value, (dict, list)) else value)
            for key, value in fields.items()
        }
        self.request("PUT", f"/api/v1/dashboard/{dashboard_id}", json=body)

    def delete_dashboard(self, dashboard_id: int) -> None:
        self.request("DELETE", f"/api/v1/dashboard/{dashboard_id}")

    # --- alerts & reports -------------------------------------------------

    def reports(self) -> list[dict]:
        return self.request("GET", "/api/v1/report/?page_size=200").get("result", [])

    def create_report(self, **fields) -> dict:
        """Create an alert or a scheduled report."""
        return self.request("POST", "/api/v1/report/", json=fields)

    def update_report(self, report_id: int, **fields) -> None:
        self.request("PUT", f"/api/v1/report/{report_id}", json=fields)

    def report_logs(self, report_id: int) -> list[dict]:
        return self.request("GET", f"/api/v1/report/{report_id}/log/").get("result", [])

    # --- export / import --------------------------------------------------

    def export_dashboard(self, dashboard_id: int) -> bytes:
        """Export a dashboard as a ZIP archive (the native export format)."""
        response = self.session.get(
            f"{self.base_url}/api/v1/dashboard/export/",
            headers={"Authorization": f"Bearer {self.token}"},
            # The export endpoint takes a rison-encoded list of dashboard ids
            # (rison spells a list `!(1,2,3)`).
            params={"q": f"!({dashboard_id})"},
            timeout=300,
        )
        if not response.ok:
            raise SupersetError(
                f"Export of dashboard {dashboard_id} failed with "
                f"{response.status_code}: {response.text[:500]}"
            )
        return response.content

    def import_dashboard(self, archive: Path, overwrite: bool = True) -> None:
        """Import a dashboard ZIP archive."""
        with archive.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/api/v1/dashboard/import/",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "X-CSRFToken": self.csrf_token or "",
                    "Referer": self.base_url,
                },
                files={
                    "zipfile": (archive.name, handle, "application/zip"),
                },
                data={"formData": json.dumps({"overwrite": overwrite, "passwords": {}})},
                timeout=300,
            )
        if not response.ok:
            raise SupersetError(
                f"Import of {archive.name} failed with {response.status_code}: "
                f"{response.text[:500]}"
            )
