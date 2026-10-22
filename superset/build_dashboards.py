#!/usr/bin/env python
"""Build the Superset dashboards that sit on top of the dbt analysis marts.

The dashboards are declared here as data — a list of chart specs and a list of
dashboard specs — and materialised through the Superset REST API. Every object
is looked up before it is created, so the script can be re-run at will
without producing duplicates.

Two things are written on purpose, because Superset needs both:

``params``
    The chart's *form data* — what the Explore UI renders. The browser
    rebuilds the query from this on every render, so this is what a user
    sees and edits.

``query_context``
    The chart's *saved query*. Superset only uses it server side, for
    ``GET /api/v1/chart/<id>/data/`` and, crucially, for scheduled reports
    and alerts — those render the chart without a browser. A chart without a
    saved query context cannot be delivered by a report.

The query context below is built to match what the Superset frontend builds
from the same form data (``buildQueryObject`` + the echarts pivot/flatten
post-processing), so a chart renders identically in the browser and in a
report.

Usage::

    set -a && source .env && set +a
    uv run python superset/build_dashboards.py

Environment:
    SUPERSET_URL             base URL of the webserver (default http://localhost:8088)
    SUPERSET_ADMIN_USERNAME  admin account
    SUPERSET_ADMIN_PASSWORD
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import SupersetClient, SupersetError  # noqa: E402

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboards"

# Superset's dashboard grid is 12 columns wide.
GRID_WIDTH = 12

# The mart each dashboard is built on. The dataset ids are resolved at run
# time from the table names, so a rebuild of the warehouse does not invalidate
# the definitions.
DATASETS = {
    "concentration": "agg_contributor_concentration",
    "activity": "agg_activity_trend",
    "backlog": "agg_issue_backlog",
    "health": "agg_repo_health",
}

# The viz types that render through the echarts post-processing chain (the
# pivot + flatten pair). Everything else gets a plain result set.
TIMESERIES_VIZ_TYPES = {
    "echarts_timeseries_bar",
    "echarts_timeseries_line",
    "echarts_timeseries_area",
    "echarts_timeseries_pie",
    "echarts_timeseries_scatter",
}

# Saved metrics that are created on the mart datasets. Superset resolves a
# metric by name against the dataset it belongs to, so an aggregation has to
# be registered on the dataset before a chart can use it.
#
# The ``sum__``/``avg__`` prefix follows Superset's own convention for
# dataset metrics and doubles as the column alias in the result set, which is
# what the pivot post-processing keys on.
DATASET_METRICS: dict[str, list[dict[str, str]]] = {
    "agg_contributor_concentration": [
        {"metric_name": "sum__top1_share_pct", "expression": 'SUM("top1_share_pct")'},
        {"metric_name": "avg__top1_share_pct", "expression": 'AVG("top1_share_pct")'},
        {"metric_name": "sum__top10_share_pct", "expression": 'SUM("top10_share_pct")'},
        {"metric_name": "avg__gini_coefficient", "expression": 'AVG("gini_coefficient")'},
        {"metric_name": "sum__contributors", "expression": 'SUM("contributors")'},
    ],
    "agg_activity_trend": [
        {"metric_name": "sum__commits", "expression": 'SUM("commits")'},
        {"metric_name": "sum__active_authors", "expression": 'SUM("active_authors")'},
        {"metric_name": "sum__prs_created", "expression": 'SUM("prs_created")'},
        {"metric_name": "sum__prs_merged", "expression": 'SUM("prs_merged")'},
        {"metric_name": "sum__issues_created", "expression": 'SUM("issues_created")'},
        {"metric_name": "sum__issues_closed", "expression": 'SUM("issues_closed")'},
    ],
    "agg_issue_backlog": [
        {"metric_name": "sum__open_issues", "expression": 'SUM("open_issues")'},
        {
            "metric_name": "sum__open_issues_under_30d",
            "expression": 'SUM("open_issues_under_30d")',
        },
        {
            "metric_name": "sum__open_issues_30_to_90d",
            "expression": 'SUM("open_issues_30_to_90d")',
        },
        {
            "metric_name": "sum__open_issues_over_90d",
            "expression": 'SUM("open_issues_over_90d")',
        },
        {"metric_name": "avg__close_rate_pct", "expression": 'AVG("close_rate_pct")'},
    ],
    "agg_repo_health": [
        {"metric_name": "avg__health_score", "expression": 'AVG("health_score")'},
        {"metric_name": "avg__activity_score", "expression": 'AVG("activity_score")'},
        {"metric_name": "avg__community_score", "expression": 'AVG("community_score")'},
        {"metric_name": "avg__backlog_score", "expression": 'AVG("backlog_score")'},
        {"metric_name": "avg__popularity_score", "expression": 'AVG("popularity_score")'},
    ],
}


# --------------------------------------------------------------------------
# Form-data helpers
# --------------------------------------------------------------------------


def _datasource(dataset_id: int) -> str:
    return f"{dataset_id}__table"


def table_params(
    dataset_id: int,
    columns: list[str],
    *,
    orderby: list[list[Any]] | None = None,
    row_limit: int = 50,
    adhoc_filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Form data for a raw-records table chart (one row per mart row)."""
    return {
        "datasource": _datasource(dataset_id),
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": columns,
        "groupby": [],
        "metrics": [],
        "orderby": orderby or [],
        "order_desc": True,
        "row_limit": row_limit,
        "page_size": row_limit,
        "server_pagination": False,
        "include_filter": True,
        "filter_bar_orientation": "vertical",
        "adhoc_filters": adhoc_filters or [],
        "time_range": "No filter",
        "granularity_sqla": None,
        "label": "",
    }


def bar_params(
    dataset_id: int,
    *,
    x_axis: str,
    metrics: list[str],
    row_limit: int = 15,
    orderby: list[list[Any]] | None = None,
    label: str | None = None,
    adhoc_filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Form data for a categorical bar chart (x axis is a plain column)."""
    return {
        "datasource": _datasource(dataset_id),
        "viz_type": "echarts_timeseries_bar",
        "x_axis": x_axis,
        "groupby": [],
        "metrics": metrics,
        "adhoc_filters": adhoc_filters or [],
        "time_range": "No filter",
        "order_desc": True,
        "orderby": orderby or [],
        "row_limit": row_limit,
        "series_limit": 0,
        "show_value": False,
        "truncate_metric": True,
        "color_scheme": "supersetColors",
        # Repository names are long: put them on the category axis so the
        # labels stay readable instead of being rotated, clipped or dropped.
        "orientation": "horizontal" if x_axis == "full_name" else "vertical",
        "xAxisLabelRotation": 0,
        "rich_tooltip": True,
        "label": label or "",
    }


def line_params(
    dataset_id: int,
    *,
    time_column: str,
    metrics: list[str],
    row_limit: int = 10000,
    label: str | None = None,
    time_range: str = "No filter",
) -> dict[str, Any]:
    """Form data for a time-series line chart."""
    return {
        "datasource": _datasource(dataset_id),
        "viz_type": "echarts_timeseries_line",
        "granularity_sqla": time_column,
        "x_axis": None,
        "groupby": [],
        "metrics": metrics,
        "adhoc_filters": [],
        "time_range": time_range,
        "order_desc": True,
        "row_limit": row_limit,
        "series_limit": 0,
        "show_value": False,
        "truncate_metric": True,
        "color_scheme": "supersetColors",
        "rich_tooltip": True,
        "label": label or "",
    }


def number_params(
    dataset_id: int,
    *,
    metric: str,
    adhoc_filters: list[dict[str, Any]] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Form data for a big-number tile."""
    return {
        "datasource": _datasource(dataset_id),
        "viz_type": "big_number_total",
        "metric": metric,
        "adhoc_filters": adhoc_filters or [],
        "time_range": "No filter",
        "subheader": "",
        "label": label or "",
    }


def equals_filter(column: str, value: Any) -> dict[str, Any]:
    """An ``adhoc_filters`` entry restricting one column to one value."""
    return {
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": "==",
        "comparator": str(value),
        "clause": "WHERE",
    }


def greater_than_filter(column: str, value: Any) -> dict[str, Any]:
    """An ``adhoc_filters`` entry keeping rows above a threshold.

    Used to restrict a ranking to the rows whose measure is actually
    known: a repository whose contributor statistics could not be ingested
    has a NULL share, and a NULL sorts first in a descending order, so it
    would push a real row out of a top-N cut.
    """
    return {
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": ">",
        "comparator": str(value),
        "clause": "WHERE",
    }


def not_null_filter(column: str) -> dict[str, Any]:
    """An ``adhoc_filters`` entry dropping NULL values of one column.

    Postgres sorts NULLs first in a ``DESC`` order, so a ranking that keeps
    the top N rows would otherwise be filled with the rows where the measure
    is undefined and render as an empty chart.
    """
    return {
        "expressionType": "SIMPLE",
        "subject": column,
        "operator": "IS NOT NULL",
        "comparator": None,
        "clause": "WHERE",
    }


# --------------------------------------------------------------------------
# Query-context builder
# --------------------------------------------------------------------------


def process_filters(params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Turn the form data's filters into the shape the backend expects.

    The frontend runs every filter through ``processFilters`` before it
    reaches the API: a *simple* filter becomes a structured clause in
    ``filters`` (``col``/``op``/``val``), while a free-form SQL filter is
    pasted into ``extras.where`` or ``extras.having``. The backend only
    understands that shape, so the same conversion has to happen here.
    """
    filters: list[dict[str, Any]] = list(params.get("filters") or [])
    where: list[str] = []
    having: list[str] = []

    for adhoc in params.get("adhoc_filters") or []:
        if adhoc.get("expressionType") == "SIMPLE":
            clause: dict[str, Any] = {
                "col": adhoc["subject"],
                "op": adhoc["operator"],
            }
            if "comparator" in adhoc:
                clause["val"] = adhoc["comparator"]
            if adhoc.get("clause") == "WHERE":
                filters.append(clause)
        else:
            expression = f"({adhoc.get('sqlExpression', '')})"
            if adhoc.get("clause") == "WHERE":
                where.append(expression)
            else:
                having.append(expression)

    extras = {
        "where": " AND ".join(where),
        "having": " AND ".join(having),
    }
    if params.get("time_grain_sqla"):
        extras["time_grain_sqla"] = params["time_grain_sqla"]
    return filters, extras


def build_query_context(params: dict[str, Any]) -> dict[str, Any]:
    """Mirror the Superset frontend's query builder for the viz types used here.

    ``extractQueryFields`` decides the query shape from ``query_mode``:

    * ``raw``      -> the columns are ``all_columns``, there are no metrics;
    * ``aggregate`` -> the columns are ``groupby``, the metrics are metrics.

    The echarts plugins then prepend the x axis to the columns and, when no
    x axis is set, turn the query into a time series over the dataset's
    temporal column. ``big_number_total`` renders a single value and goes
    through neither.
    """
    viz_type = params.get("viz_type")
    query_mode = params.get("query_mode", "aggregate")
    groupby = list(params.get("groupby") or [])
    metrics = list(params.get("metrics") or [])
    if not metrics and params.get("metric"):
        # ``big_number_total`` stores its metric under the singular key.
        metrics = [params["metric"]]
    all_columns = list(params.get("all_columns") or [])
    x_axis = params.get("x_axis")
    granularity_sqla = params.get("granularity_sqla")

    is_x_axis_set = isinstance(x_axis, str) and x_axis != ""
    is_timeseries_chart = viz_type in TIMESERIES_VIZ_TYPES

    if query_mode == "raw":
        # Raw records: a plain projection of the selected columns.
        columns = list(all_columns)
        metrics = []
        x_axis_label = ""
    elif is_x_axis_set:
        columns = [x_axis] + groupby
        x_axis_label = x_axis
    else:
        # No explicit axis: the chart is a time series over the temporal
        # column, which the backend exposes as ``__timestamp``.
        columns = list(groupby)
        x_axis_label = "__timestamp"

    filters, extras = process_filters(params)

    query: dict[str, Any] = {
        "columns": columns,
        "filters": filters,
        "extras": extras,
        "row_limit": params.get("row_limit", 10000),
        "row_offset": 0,
        "order_desc": params.get("order_desc", True),
        "orderby": list(params.get("orderby") or []),
        "annotation_layers": [],
        "applied_time_extras": {},
        "time_offsets": [],
        "url_params": {},
        "custom_params": {},
        "custom_form_data": {},
        "series_columns": groupby,
        "series_limit": 0,
        "group_others_when_limit_reached": False,
        "time_range": params.get("time_range", "No filter"),
    }

    # A raw-records query carries no metrics at all — sending an empty list
    # would make the backend group the rows instead of projecting them.
    if query_mode != "raw":
        query["metrics"] = metrics

    if granularity_sqla:
        query["granularity"] = granularity_sqla

    if is_timeseries_chart and not is_x_axis_set:
        query["is_timeseries"] = True

    post_processing: list[dict[str, Any]] = []
    if is_timeseries_chart:
        # The echarts plugins pivot the result into one column per series and
        # then flatten it back into a plain frame.
        if x_axis_label and metrics:
            post_processing.append(
                {
                    "operation": "pivot",
                    "options": {
                        "index": [x_axis_label],
                        "columns": list(groupby),
                        "aggregates": {metric: {"operator": "mean"} for metric in metrics},
                        "drop_missing_columns": True,
                    },
                }
            )
        post_processing.append({"operation": "flatten"})
    query["post_processing"] = post_processing

    return {
        "datasource": {
            "id": int(str(params["datasource"]).split("__")[0]),
            "type": "table",
        },
        "result_format": "json",
        "result_type": "full",
        "queries": [query],
    }


# --------------------------------------------------------------------------
# Chart specifications
# --------------------------------------------------------------------------
#
# ``position`` is (x, y, width, height) in dashboard grid units.

CHART_SPECS: list[dict[str, Any]] = [
    # --- Contributor concentration ---------------------------------------
    {
        "key": "cc-bus-factor",
        "dataset": "concentration",
        "name": "Bus factor by repository",
        "description": (
            "Contribution concentration per repository: how much of the commit "
            "history belongs to the single most active contributor."
        ),
        "position": (0, 0, 12, 72),
        "build": lambda d: table_params(
            d,
            [
                "full_name",
                "language",
                "contributors",
                "top1_share_pct",
                "top10_share_pct",
                "gini_coefficient",
                "bus_factor",
            ],
            orderby=[["contributors", False]],
            row_limit=200,
        ),
    },
    {
        "key": "cc-top1-share",
        "dataset": "concentration",
        "name": "Largest single-contributor share",
        "description": (
            "Top 15 repositories by the share of commits owned by their most "
            "active contributor — a proxy for key-person risk. Only "
            "repositories with contributor statistics are ranked."
        ),
        "position": (0, 9, 6, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="full_name",
            metrics=["sum__top1_share_pct"],
            row_limit=15,
            orderby=[["sum__top1_share_pct", False]],
            adhoc_filters=[greater_than_filter("total_commits", 0)],
        ),
    },
    {
        "key": "cc-bus-factor-dist",
        "dataset": "concentration",
        "name": "Bus factor distribution",
        "description": (
            "How many repositories fall into each bus-factor band: 1 means a "
            "single maintainer owns everything, 4 means the top 10 "
            "contributors hold less than 80% of the commits. Repositories "
            "without contributor statistics are excluded — their bus factor "
            "is unknown."
        ),
        "position": (6, 9, 6, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="bus_factor",
            metrics=["count"],
            row_limit=10,
            orderby=[["bus_factor", True]],
            adhoc_filters=[greater_than_filter("total_commits", 0)],
        ),
    },
    {
        "key": "cc-single-maintainer",
        "dataset": "concentration",
        "name": "Repositories with a single maintainer",
        "description": "Count of repositories where one contributor wrote all the commits.",
        "position": (0, 17, 6, 48),
        "build": lambda d: number_params(
            d,
            metric="count",
            adhoc_filters=[
                equals_filter("contributors", 1),
                greater_than_filter("total_commits", 0),
            ],
        ),
    },
    {
        "key": "cc-share-by-language",
        "dataset": "concentration",
        "name": "Average top-1 share by language",
        "description": "Mean single-contributor share, grouped by primary language.",
        "position": (6, 17, 6, 48),
        "build": lambda d: bar_params(
            d,
            x_axis="language",
            metrics=["avg__top1_share_pct"],
            row_limit=20,
            orderby=[["avg__top1_share_pct", False]],
        ),
    },
    # --- Activity trend --------------------------------------------------
    {
        "key": "at-commits",
        "dataset": "activity",
        "name": "Commits per week",
        "description": "Portfolio-wide commit volume per ISO week.",
        "position": (0, 0, 6, 64),
        "build": lambda d: line_params(
            d,
            time_column="week_start",
            metrics=["sum__commits"],
            time_range="Last 3 months",
        ),
    },
    {
        "key": "at-prs",
        "dataset": "activity",
        "name": "Pull requests created vs merged per week",
        "description": "Weekly pull request inflow versus merges.",
        "position": (6, 0, 6, 64),
        "build": lambda d: line_params(
            d,
            time_column="week_start",
            metrics=["sum__prs_created", "sum__prs_merged"],
            time_range="Last 3 months",
        ),
    },
    {
        "key": "at-issues",
        "dataset": "activity",
        "name": "Issues created vs closed per week",
        "description": "Weekly issue inflow versus resolutions.",
        "position": (0, 8, 6, 64),
        "build": lambda d: line_params(
            d,
            time_column="week_start",
            metrics=["sum__issues_created", "sum__issues_closed"],
            time_range="Last 3 months",
        ),
    },
    {
        "key": "at-authors",
        "dataset": "activity",
        "name": "Active authors per week",
        "description": "Distinct commit authors active in each week.",
        "position": (6, 8, 6, 64),
        "build": lambda d: line_params(
            d,
            time_column="week_start",
            metrics=["sum__active_authors"],
            time_range="Last 3 months",
        ),
    },
    {
        "key": "at-detail",
        "dataset": "activity",
        "name": "Recent weekly activity",
        "description": "Raw weekly rows: commits, authors, pull requests and issues.",
        "position": (0, 16, 12, 64),
        "build": lambda d: table_params(
            d,
            [
                "full_name",
                "language",
                "week_start",
                "commits",
                "active_authors",
                "prs_created",
                "prs_merged",
                "issues_created",
                "issues_closed",
            ],
            orderby=[["week_start", False]],
            row_limit=50,
        ),
    },
    # --- Issue backlog ----------------------------------------------------
    {
        "key": "ib-open",
        "dataset": "backlog",
        "name": "Open issues by repository",
        "description": "Repositories ranked by the number of open issues.",
        "position": (0, 0, 6, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="full_name",
            metrics=["sum__open_issues"],
            row_limit=20,
            orderby=[["sum__open_issues", False]],
        ),
    },
    {
        "key": "ib-age",
        "dataset": "backlog",
        "name": "Backlog age buckets",
        "description": (
            "Open issues per repository split into age buckets: under 30 days, "
            "30 to 90 days, and over 90 days."
        ),
        "position": (6, 0, 6, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="full_name",
            metrics=[
                "sum__open_issues_under_30d",
                "sum__open_issues_30_to_90d",
                "sum__open_issues_over_90d",
            ],
            row_limit=15,
            orderby=[["sum__open_issues_over_90d", False]],
        ),
    },
    {
        "key": "ib-close-rate",
        "dataset": "backlog",
        "name": "Issue close rate by repository",
        "description": "Share of issues that were closed, per repository.",
        "position": (0, 8, 6, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="full_name",
            metrics=["avg__close_rate_pct"],
            row_limit=20,
            orderby=[["avg__close_rate_pct", False]],
            adhoc_filters=[not_null_filter("close_rate_pct")],
        ),
    },
    {
        "key": "ib-table",
        "dataset": "backlog",
        "name": "Backlog summary",
        "description": "Per-repository backlog, close rate and median age of open issues.",
        "position": (6, 8, 6, 64),
        "build": lambda d: table_params(
            d,
            [
                "full_name",
                "language",
                "total_issues",
                "open_issues",
                "closed_issues",
                "close_rate_pct",
                "median_open_age_days",
                "open_issues_over_90d",
            ],
            orderby=[["open_issues", False]],
            row_limit=50,
        ),
    },
    {
        "key": "ib-total-open",
        "dataset": "backlog",
        "name": "Open issues across the portfolio",
        "description": "Total number of open issues in every tracked repository.",
        "position": (0, 16, 12, 40),
        "build": lambda d: number_params(d, metric="sum__open_issues"),
    },
    # --- Repository health ------------------------------------------------
    {
        "key": "rh-scoreboard",
        "dataset": "health",
        "name": "Repository health scoreboard",
        "description": (
            "Composite health score per repository with its activity, community, "
            "backlog and popularity components."
        ),
        "position": (0, 0, 12, 72),
        "build": lambda d: table_params(
            d,
            [
                "full_name",
                "language",
                "health_score",
                "health_band",
                "activity_score",
                "community_score",
                "backlog_score",
                "popularity_score",
                "commits",
                "contributors",
                "issues_open",
                "last_commit_date",
            ],
            orderby=[["health_score", False]],
            row_limit=200,
        ),
    },
    {
        "key": "rh-band",
        "dataset": "health",
        "name": "Health band distribution",
        "description": "How many repositories fall into each health band.",
        "position": (0, 9, 6, 56),
        "build": lambda d: bar_params(
            d,
            x_axis="health_band",
            metrics=["count"],
            row_limit=10,
            orderby=[["health_band", True]],
        ),
    },
    {
        "key": "rh-top",
        "dataset": "health",
        "name": "Top repositories by health score",
        "description": "The 20 healthiest repositories in the portfolio.",
        "position": (6, 9, 6, 56),
        "build": lambda d: bar_params(
            d,
            x_axis="full_name",
            metrics=["avg__health_score"],
            row_limit=20,
            orderby=[["avg__health_score", False]],
        ),
    },
    {
        "key": "rh-components",
        "dataset": "health",
        "name": "Health components by language",
        "description": (
            "Average activity, community, backlog and popularity scores, "
            "grouped by primary language."
        ),
        "position": (0, 16, 12, 64),
        "build": lambda d: bar_params(
            d,
            x_axis="language",
            metrics=[
                "avg__activity_score",
                "avg__community_score",
                "avg__backlog_score",
                "avg__popularity_score",
            ],
            row_limit=20,
            orderby=[["avg__activity_score", False]],
        ),
    },
]


# --------------------------------------------------------------------------
# Dashboard specifications
# --------------------------------------------------------------------------

DASHBOARD_SPECS: list[dict[str, Any]] = [
    {
        "slug": "contributor-concentration",
        "title": "Contributor Concentration",
        "description": (
            "Key-person risk across the tracked repositories: how concentrated "
            "each commit history is, and which projects depend on a single "
            "maintainer."
        ),
        "dataset": "concentration",
        "charts": [
            "cc-bus-factor",
            "cc-top1-share",
            "cc-bus-factor-dist",
            "cc-single-maintainer",
            "cc-share-by-language",
        ],
        "filters": [
            {"name": "Language", "column": "language", "dataset": "concentration"},
            {"name": "Owner", "column": "owner_login", "dataset": "concentration"},
        ],
    },
    {
        "slug": "activity-trend",
        "title": "Activity Trend",
        "description": (
            "How the portfolio moves over time: commit volume, pull request and "
            "issue throughput, and the number of people behind it."
        ),
        "dataset": "activity",
        "charts": ["at-commits", "at-prs", "at-issues", "at-authors", "at-detail"],
        "filters": [
            {"name": "Language", "column": "language", "dataset": "activity"},
            {"name": "Repository", "column": "full_name", "dataset": "activity"},
        ],
    },
    {
        "slug": "issue-backlog",
        "title": "Issue Backlog",
        "description": (
            "Open issue load per repository, how old it gets, and how much of "
            "it is actually being closed."
        ),
        "dataset": "backlog",
        "charts": ["ib-open", "ib-age", "ib-close-rate", "ib-table", "ib-total-open"],
        "filters": [
            {"name": "Language", "column": "language", "dataset": "backlog"},
            {"name": "Owner", "column": "owner_login", "dataset": "backlog"},
        ],
    },
    {
        "slug": "repository-health",
        "title": "Repository Health",
        "description": (
            "A composite health score per repository, combining activity, "
            "community, backlog and popularity."
        ),
        "dataset": "health",
        "charts": ["rh-scoreboard", "rh-band", "rh-top", "rh-components"],
        "filters": [
            {"name": "Language", "column": "language", "dataset": "health"},
            {"name": "Health band", "column": "health_band", "dataset": "health"},
            {"name": "Owner", "column": "owner_login", "dataset": "health"},
        ],
    },
]


# --------------------------------------------------------------------------
# Layout helpers
# --------------------------------------------------------------------------


def build_position(
    chart_ids: list[int],
    placements: dict[str, tuple[int, int, int, int]],
    charts: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Lay the charts out on the 12-column grid Superset uses.

    ``placements`` maps a chart id (as a string) to ``(x, y, width, height)``:
    ``width`` is measured in grid columns (1-12), ``height`` in grid units of
    8px (we use 48-72, i.e. 384-576px). Charts sharing a ``y`` land in the same
    row; ``x`` only decides their order inside that row.

    Superset renders a layout only when it is the tree the dashboard editor
    builds: ``ROOT -> GRID -> ROW -> COLUMN -> CHART`` with ``parents``
    recorded at every level. A flat layout still shows the chart titles, but
    the grid resolves each slot to a zero-width box, so the charts draw
    nothing.
    """
    charts = charts or {}
    rows: dict[int, list[tuple[int, int, int, int]]] = {}
    for chart_id in chart_ids:
        x, y, width, height = placements[str(chart_id)]
        rows.setdefault(y, []).append((x, chart_id, width, height))

    position: dict[str, Any] = {"DASHBOARD_VERSION_KEY": "v2"}
    row_keys: list[str] = []
    for row_index, (_, items) in enumerate(sorted(rows.items())):
        row_key = f"ROW-{row_index}"
        column_keys: list[str] = []
        for column_index, (_, chart_id, width, height) in enumerate(sorted(items)):
            column_key = f"COLUMN-{row_index}-{column_index}"
            chart_key = f"CHART-{chart_id}"
            chart = charts.get(chart_id, {})
            meta: dict[str, Any] = {
                "chartId": chart_id,
                "width": width,
                "height": height,
                "sliceName": chart.get("slice_name", ""),
            }
            if chart.get("uuid"):
                meta["uuid"] = chart["uuid"]
            position[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_key, column_key],
                "meta": meta,
            }
            position[column_key] = {
                "type": "COLUMN",
                "id": column_key,
                "children": [chart_key],
                "parents": ["ROOT_ID", "GRID_ID", row_key],
                "meta": {"width": width, "background": "BACKGROUND_TRANSPARENT"},
            }
            column_keys.append(column_key)
        position[row_key] = {
            "type": "ROW",
            "id": row_key,
            "children": column_keys,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        row_keys.append(row_key)

    position["GRID_ID"] = {
        "type": "GRID",
        "id": "GRID_ID",
        "children": row_keys,
        "parents": ["ROOT_ID"],
        "meta": {},
    }
    position["ROOT_ID"] = {
        "type": "ROOT",
        "id": "ROOT_ID",
        "children": ["GRID_ID"],
        "meta": {},
    }
    return position


def native_filter(
    filter_id: str,
    name: str,
    column: str,
    dataset_id: int,
    chart_ids: list[int],
) -> dict[str, Any]:
    """A dashboard-native select filter.

    The shape mirrors what the Superset UI writes into the dashboard's
    ``json_metadata``: a filter with a target column, a scope covering the
    whole dashboard, and a default (empty) data mask.
    """
    return {
        "id": filter_id,
        "name": name,
        "filterType": "filter_select",
        "type": "NATIVE_FILTER",
        "description": "",
        "targets": [
            {
                "datasetId": dataset_id,
                "column": {"name": column, "displayName": column},
            }
        ],
        "defaultDataMask": {"filterState": {"value": None}},
        "cascadeParentIds": [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        "controlValues": {
            "multiSelect": True,
            "enableEmptyFilter": False,
            "inverseSelection": False,
            "creatable": False,
            "allowsMultipleValues": True,
            "isRequired": False,
        },
        "chartsInScope": list(chart_ids),
    }


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------


def log(message: str) -> None:
    print(f"[dashboards] {message}", flush=True)


def resolve_datasets(client: SupersetClient) -> dict[str, int]:
    """Map the mart names to their Superset dataset ids."""
    datasets = client.datasets()
    by_table = {dataset["table_name"]: dataset for dataset in datasets}
    resolved: dict[str, int] = {}
    for key, table_name in DATASETS.items():
        dataset = by_table.get(table_name)
        if not dataset:
            raise SupersetError(f"Dataset for table {table_name!r} does not exist")
        resolved[key] = dataset["id"]
    return resolved


def refresh_datasets(client: SupersetClient, ids: list[int]) -> None:
    """Re-introspect the mart tables so new columns show up."""
    for dataset_id in ids:
        client.refresh_dataset(dataset_id)
    log(f"Refreshed {len(ids)} datasets")


def ensure_dataset_metrics(client: SupersetClient, dataset_id: int, table_name: str) -> None:
    """Register the aggregation metrics the charts rely on.

    Superset resolves a metric by name against the dataset that owns it, so
    ``sum__commits`` only works once the dataset carries a metric with that
    name. The update endpoint *replaces* the metric list, so the existing
    metrics (``count`` in particular) have to be sent back along with the new
    ones.
    """
    wanted = DATASET_METRICS.get(table_name)
    if not wanted:
        return

    dataset = client.dataset(dataset_id)
    existing = {metric["metric_name"]: metric for metric in dataset.get("metrics", [])}

    metrics: list[dict[str, Any]] = []
    for metric in dataset.get("metrics", []):
        metrics.append(
            {
                "id": metric["id"],
                "metric_name": metric["metric_name"],
                "expression": metric["expression"],
                "verbose_name": metric.get("verbose_name"),
                "description": metric.get("description"),
                "metric_type": metric.get("metric_type"),
                "d3format": metric.get("d3format"),
                "warning_text": metric.get("warning_text"),
                "extra": metric.get("extra"),
                "currency": metric.get("currency"),
                "uuid": metric.get("uuid"),
            }
        )

    added = []
    for metric in wanted:
        if metric["metric_name"] in existing:
            continue
        metrics.append(
            {
                "metric_name": metric["metric_name"],
                "expression": metric["expression"],
                "verbose_name": metric["metric_name"],
                "metric_type": "postgresql",
            }
        )
        added.append(metric["metric_name"])

    if not added:
        return

    client.update_dataset(dataset_id, metrics=metrics)
    log(f"Dataset {table_name}: added metrics {', '.join(added)}")


def upsert_chart(
    client: SupersetClient,
    *,
    dataset_id: int,
    name: str,
    viz_type: str,
    params: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    """Create the chart, or update it when it already exists.

    Returns the chart record (at least ``id``, ``uuid`` and ``slice_name``);
    the layout needs the uuid to render the chart slot.
    """
    query_context = build_query_context(params)
    existing = {chart["slice_name"]: chart for chart in client.charts()}
    chart = existing.get(name)

    if chart:
        client.update_chart(
            chart["id"],
            datasource_id=dataset_id,
            datasource_type="table",
            slice_name=name,
            viz_type=viz_type,
            params=params,
            query_context=query_context,
            description=description,
        )
        return chart

    chart_id = client.create_chart(
        dataset_id=dataset_id,
        slice_name=name,
        viz_type=viz_type,
        params=params,
        query_context=query_context,
        description=description,
    )
    return client.request("GET", f"/api/v1/chart/{chart_id}")["result"]


def upsert_dashboard(
    client: SupersetClient,
    *,
    title: str,
    slug: str,
    position: dict[str, Any],
    json_metadata: dict[str, Any],
) -> int:
    """Create the dashboard, or update it when it already exists.

    The layout has to travel *inside* ``json_metadata`` as well as in
    ``position_json``. Superset derives the dashboard's chart association
    (``dashboard_slices``) from ``json_metadata["positions"]``; a dashboard
    whose relation is empty renders every slot as "no chart definition
    associated with this component".
    """
    metadata = {**json_metadata, "positions": position}
    existing = {dash["slug"]: dash for dash in client.dashboards()}
    dashboard = existing.get(slug)

    if dashboard:
        client.update_dashboard(
            dashboard["id"],
            dashboard_title=title,
            slug=slug,
            position_json=position,
            json_metadata=metadata,
            published=True,
        )
        return dashboard["id"]

    dashboard_id = client.create_dashboard(
        dashboard_title=title,
        slug=slug,
        position=position,
        json_metadata=metadata,
    )
    # Creating a dashboard does not link its charts; replaying the layout as
    # an update is what establishes the association.
    client.update_dashboard(
        dashboard_id,
        dashboard_title=title,
        slug=slug,
        position_json=position,
        json_metadata=metadata,
        published=True,
    )
    return dashboard_id


def main() -> int:
    client = SupersetClient(
        base_url=os.environ.get("SUPERSET_URL", "http://localhost:8088"),
        username=os.environ.get("SUPERSET_ADMIN_USERNAME", "admin"),
        password=os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin"),
    )
    client.wait_until_healthy()
    client.login()
    log("Authenticated")

    dataset_ids = resolve_datasets(client)
    refresh_datasets(client, sorted(set(dataset_ids.values())))
    for key, table_name in DATASETS.items():
        ensure_dataset_metrics(client, dataset_ids[key], table_name)

    # --- charts ----------------------------------------------------------
    chart_ids: dict[str, int] = {}
    chart_records: dict[int, dict[str, Any]] = {}
    placements: dict[str, tuple[int, int, int, int]] = {}
    for spec in CHART_SPECS:
        dataset_id = dataset_ids[spec["dataset"]]
        params = spec["build"](dataset_id)
        chart = upsert_chart(
            client,
            dataset_id=dataset_id,
            name=spec["name"],
            viz_type=params["viz_type"],
            params=params,
            description=spec["description"],
        )
        chart_ids[spec["key"]] = chart["id"]
        chart_records[chart["id"]] = chart
        placements[spec["key"]] = spec["position"]
        log(f"Chart {spec['name']!r} -> id {chart['id']}")

    # --- dashboards ------------------------------------------------------
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    for spec in DASHBOARD_SPECS:
        ids = [chart_ids[key] for key in spec["charts"]]
        grid_placements = {str(chart_ids[key]): placements[key] for key in spec["charts"]}
        position = build_position(ids, grid_placements, chart_records)

        filters = [
            native_filter(
                filter_id=f"NATIVE_FILTER-{spec['slug']}-{index}",
                name=entry["name"],
                column=entry["column"],
                dataset_id=dataset_ids[entry["dataset"]],
                chart_ids=ids,
            )
            for index, entry in enumerate(spec["filters"])
        ]
        json_metadata = {
            "native_filter_configuration": filters,
            "chart_configuration": {},
            "global_chart_configuration": {"crossFilters": {}},
            "refresh_frequency": 0,
            "expanded_slices": {},
            "shared_label_colors": {},
            "label_colors": {},
            "filter_scopes": {},
            "color_scheme": "supersetColors",
            "cross_filters_enabled": True,
        }

        dashboard_id = upsert_dashboard(
            client,
            title=spec["title"],
            slug=spec["slug"],
            position=position,
            json_metadata=json_metadata,
        )
        log(f"Dashboard {spec['title']!r} -> id {dashboard_id}")

        archive = DASHBOARD_DIR / f"{spec['slug']}.zip"
        archive.write_bytes(client.export_dashboard(dashboard_id))
        log(f"Exported {archive}")

    log("Done")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SupersetError as error:
        log(f"ERROR: {error}")
        sys.exit(1)
