"""Superset configuration for the GitHub analytics warehouse.

Loaded by the Superset application through the ``SUPERSET_CONFIG_PATH``
environment variable (see ``docker-compose.superset.yml``). Every value comes
from the environment so nothing secret lives in the repository.

Two things worth knowing:

* The warehouse is read-only. The connection uses the ``superset_ro`` role,
  which only holds ``SELECT`` on the ``public`` schema. Superset therefore
  cannot mutate the data the dbt project owns.
* The metadata database is separate from the analytics database: Superset
  keeps its own state in the ``superset`` database inside the same Postgres
  instance, and never touches the ``public`` schema of the analytics one.
"""

import os
from pathlib import Path

from celery.schedules import crontab


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# --- Core -----------------------------------------------------------------

SECRET_KEY = _env("SUPERSET_SECRET_KEY")
SQLALCHEMY_DATABASE_URI = _env(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg2://superset:superset@postgres:5432/superset",
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# The example datasets are large and irrelevant here: every dashboard is
# built on the dbt marts instead.
SUPERSET_LOAD_EXAMPLES = False

# Uploaded files and temporary artefacts.
UPLOAD_FOLDER = "/app/superset_home/uploads"
DATA_DIR = "/app/superset_home/data"

# --- Redis / cache / Celery ----------------------------------------------

REDIS_HOST = _env("REDIS_HOST", "superset-redis")
REDIS_PORT = int(_env("REDIS_PORT", "6379"))

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60 * 60 * 24,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
}
DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60 * 60 * 24,
    "CACHE_KEY_PREFIX": "superset_data_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
}
FILTER_STATE_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60 * 60 * 24 * 7,
    "CACHE_KEY_PREFIX": "superset_filter_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/2",
}
EXPLORE_FORM_DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60 * 60 * 24,
    "CACHE_KEY_PREFIX": "superset_explore_",
    "CACHE_REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/3",
}


class CeleryConfig:
    """Celery settings used by the worker and beat processes.

    The task modules match what Superset 6.1 ships: `superset.sql_lab` for
    SQL Lab queries, `superset.tasks.scheduler` for the reports scheduler
    (which is what actually dispatches alerts and scheduled reports),
    plus the thumbnail, cache and Slack helpers.
    """

    broker_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/4"
    result_backend = f"redis://{REDIS_HOST}:{REDIS_PORT}/5"
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.thumbnails",
        "superset.tasks.cache",
        "superset.tasks.slack",
    )
    worker_prefetch_multiplier = 1
    task_acks_late = False
    worker_max_tasks_per_child = 128
    beat_schedule = {
        # Dispatch due alerts and scheduled reports.
        #
        # The schedule runs every minute on purpose. Superset matches a
        # report's crontab against a window of `ALERT_REPORTS_CRON_WINDOW_SIZE`
        # seconds around the moment the scheduler task runs, so the task has
        # to run at least as often as the smallest interval a report may use.
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": crontab(minute="*", hour="*"),
        },
        # Keep the report log from growing without bound.
        "reports.prune_log": {
            "task": "reports.prune_log",
            "schedule": crontab(minute=0, hour=0),
        },
    }
    feature_flags = {
        "ALERT_REPORTS": True,
        "DASHBOARD_NATIVE_FILTERS": True,
        "DASHBOARD_RBAC": True,
        "EMBEDDED_SUPERSET": False,
        "ENABLE_TEMPLATE_PROCESSING": True,
        "SCHEDULED_QUERIES": True,
    }


CELERY_CONFIG = CeleryConfig

# --- Alerts & scheduled reports -------------------------------------------

ENABLE_ALERT_REPORTS = True
SCREENSHOT_LOCATE_PATH = Path("/app/superset_home/screenshots")

# The worker fetches the chart data over HTTP before it builds the report
# attachment, so it needs an address that resolves inside the compose
# network — the webserver lives in its own container.
WEBDRIVER_BASEURL = _env("SUPERSET_BASEURL", "http://superset:8088/")
# The link a human follows from the e-mail.
WEBDRIVER_BASEURL_USER_FRIENDLY = _env("SUPERSET_BASEURL_USER_FRIENDLY", "http://localhost:8088/")

# E-mail delivery for report attachments and alert notifications. Set
# SMTP_HOST to enable it; when it is empty the features stay available but
# cannot deliver anything.
#
# The key names are Superset's own (SMTP_STARTTLS/SMTP_SSL/SMTP_USER) — they
# are not the Airflow ones, and a typo here silently falls back to the
# default "starttls on localhost:25".
SMTP_HOST = _env("SUPERSET_SMTP_HOST")
SMTP_PORT = int(_env("SUPERSET_SMTP_PORT", "25"))
SMTP_USER = _env("SUPERSET_SMTP_USERNAME")
SMTP_PASSWORD = _env("SUPERSET_SMTP_PASSWORD")
SMTP_STARTTLS = _env_bool("SUPERSET_SMTP_USE_TLS", False)
SMTP_SSL = _env_bool("SUPERSET_SMTP_USE_SSL", False)
SMTP_MAIL_FROM = _env("SUPERSET_SMTP_FROM", "superset@superset.local")
EMAIL_NOTIFICATIONS = bool(SMTP_HOST)
# Deliver for real. The flag exists so a staging instance can exercise the
# report pipeline without mailing anybody; here the mail catcher in the
# compose overlay is the sink, so delivery is switched on.
ALERT_REPORTS_NOTIFICATION_DRY_RUN = False

# --- Query execution -----------------------------------------------------

# The warehouse is small, but a runaway query should not hold a worker
# slot forever.
SQLLAB_TIMEOUT = int(_env("SUPERSET_SQLLAB_TIMEOUT", "300"))
SUPERSET_WEBSERVER_TIMEOUT = int(_env("SUPERSET_WEBSERVER_TIMEOUT", "300"))
SQLLAB_CTAS_NO_LIMIT = False

# Result rows kept in the cache before the result is offloaded to disk.
CACHE_DEFAULT_TIMEOUT = 60 * 60 * 24

# --- UI / behaviour -------------------------------------------------------

ROW_LIMIT = int(_env("SUPERSET_ROW_LIMIT", "25000"))
SAMPLES_ROW_LIMIT = 1000
SUPERSET_WEBSERVER_PORT = 8088
DEFAULT_FEATURE_FLAGS = {
    "ALERT_REPORTS": True,
    "DASHBOARD_NATIVE_FILTERS": True,
    "EMBEDDED_SUPERSET": False,
}
