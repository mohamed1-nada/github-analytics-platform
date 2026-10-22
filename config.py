import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load the project's .env explicitly (not by searching from the CWD) so the
# settings are the same whether the pipeline runs from the repo root, from
# Airflow, or from a notebook in another directory.
load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_REPOS = [
    ("torvalds", "linux"),
    ("facebook", "react"),
    ("microsoft", "vscode"),
]


def _get(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


@dataclass
class Settings:
    github_token: str = field(default_factory=lambda: _get("GITHUB_TOKEN", default=""))
    base_url: str = field(
        default_factory=lambda: _get("BASE_URL", default="https://api.github.com")
    )

    pg_host: str = field(default_factory=lambda: _get("PGHOST", "DBHOST", default="localhost"))
    pg_database: str = field(
        default_factory=lambda: _get("PGDATABASE", "DATABASE_NAME", default="")
    )
    pg_user: str = field(default_factory=lambda: _get("PGUSER", "DBUSER", default=""))
    pg_password: str = field(default_factory=lambda: _get("PGPASSWORD", "DBPASSWORD", default=""))
    # Deliberately not `PORT`: that name is claimed by many web hosts for the
    # HTTP port and would silently point the pipeline at the wrong database.
    pg_port: str = field(default_factory=lambda: _get("PGPORT", "DBPORT", default="5432"))

    batch_size: int = field(default_factory=lambda: int(os.environ.get("BATCH_SIZE", "100")))
    lookback_days: int = field(default_factory=lambda: int(os.environ.get("LOOKBACK_DAYS", "30")))
    max_pages: int = field(default_factory=lambda: int(os.environ.get("MAX_PAGES", "50")))

    def default_since(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self.lookback_days)

    def default_until(self) -> datetime:
        return datetime.now(UTC)

    def require_database_settings(self) -> None:
        """Fail fast with an actionable message when the .env is incomplete."""
        missing = [
            name
            for name, value in (
                ("PGDATABASE / DATABASE_NAME", self.pg_database),
                ("PGUSER / DBUSER", self.pg_user),
                ("PGPASSWORD / DBPASSWORD", self.pg_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing database settings: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
