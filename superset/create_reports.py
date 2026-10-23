"""Create the alert and the scheduled report that ship with the dashboards.

Both objects live in Superset's metadata database, not in the dashboard
archives, so they are created here and nowhere else. The script is
idempotent: it looks each schedule up by name and updates it in place, so
re-running the builder never duplicates an alert or a report.

Run it after the dashboards exist::

    set -a && source .env && set +a
    uv run python superset/create_reports.py
"""

from __future__ import annotations

import os
import sys
from typing import Any

from api_client import SupersetClient

# The charts the two schedules are attached to. Superset requires every
# schedule to reference a chart or a dashboard; for an alert the chart's data
# is what the e-mail embeds, for a CSV report it is what gets attached.
ALERT_CHART_NAME = "At-risk repositories"
REPORT_CHART_NAME = "Repository health scoreboard"

# Every repository whose health score falls into the "At risk" band. The
# alert counts them and fires as soon as there is at least one.
AT_RISK_SQL = """
SELECT count(*) AS repos_at_risk
FROM public.agg_repo_health
WHERE health_band = 'At risk'
""".strip()


def recipients() -> list[dict[str, str]]:
    """The e-mail recipients, from ``SUPERSET_REPORT_RECIPIENTS``.

    The addresses do not have to exist: the compose overlay points Superset
    at the Mailpit catcher, which accepts anything.
    """
    raw = os.environ.get("SUPERSET_REPORT_RECIPIENTS", "analytics@example.com")
    return [
        {"type": "Email", "recipient_config_json": {"target": address.strip()}}
        for address in raw.split(",")
        if address.strip()
    ]


def build_schedules(
    *,
    alert_chart_id: int,
    report_chart_id: int,
    database_id: int,
    owner_id: int | None,
    who: list[dict],
) -> list[dict[str, Any]]:
    """The alert and the report, in the shape the REST API expects."""
    return [
        {
            "type": "Alert",
            "name": "Repositories at risk",
            "description": (
                "Fires when at least one repository in the portfolio has a "
                "health score in the 'At risk' band."
            ),
            "active": True,
            "crontab": "0 8 * * *",
            "timezone": "UTC",
            "database": database_id,
            "sql": AT_RISK_SQL,
            "chart": alert_chart_id,
            "validator_type": "operator",
            "validator_config_json": {"op": ">", "threshold": 0.0},
            "report_format": "TEXT",
            "recipients": who,
            "owners": [owner_id] if owner_id else [],
            # `alerts_reports` keeps the recipients above. The other creation
            # methods exist for the UI's "create from chart/dashboard" flow
            # and silently replace them with the current user's address.
            "creation_method": "alerts_reports",
            "grace_period": 60 * 60 * 4,
            "working_timeout": 60 * 60,
        },
        {
            "type": "Report",
            "name": "Weekly repository health scoreboard",
            "description": (
                "Every Monday morning, mail the repository health scoreboard as a CSV attachment."
            ),
            "active": True,
            "crontab": "0 7 * * 1",
            "timezone": "UTC",
            # Superset only builds a CSV for a *chart*: a dashboard report in
            # CSV format is delivered as a bare link. The scoreboard table is
            # the artefact worth mailing anyway.
            "chart": report_chart_id,
            "report_format": "CSV",
            "recipients": who,
            "owners": [owner_id] if owner_id else [],
            "creation_method": "alerts_reports",
            "grace_period": 60 * 60 * 4,
            "working_timeout": 60 * 60,
        },
    ]


def upsert(client: SupersetClient, schedule: dict[str, Any]) -> int:
    """Create the schedule, or update the one that already bears its name."""
    existing = {report["name"]: report for report in client.reports()}
    current = existing.get(schedule["name"])
    if current:
        client.update_report(current["id"], **schedule)
        return current["id"]
    return client.create_report(**schedule)["id"]


def main() -> int:
    client = SupersetClient(
        base_url=os.environ.get("SUPERSET_URL", "http://localhost:8088"),
        username=os.environ.get("SUPERSET_ADMIN_USERNAME", "admin"),
        password=os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"),
    )
    client.wait_until_healthy()
    client.login()

    charts = {chart["slice_name"]: chart for chart in client.charts()}
    missing = [name for name in (ALERT_CHART_NAME, REPORT_CHART_NAME) if name not in charts]
    if missing:
        raise SystemExit(f"Charts {missing} are missing; build the dashboards first")

    database = client.database_by_name("GitHub Analytics")
    if not database:
        raise SystemExit("Database 'GitHub Analytics' is missing; run superset/bootstrap.py first")

    schedules = build_schedules(
        alert_chart_id=charts[ALERT_CHART_NAME]["id"],
        report_chart_id=charts[REPORT_CHART_NAME]["id"],
        database_id=database["id"],
        owner_id=client.user_id,
        who=recipients(),
    )
    for schedule in schedules:
        schedule_id = upsert(client, schedule)
        print(f"[reports] {schedule['type']} {schedule['name']!r} -> id {schedule_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
