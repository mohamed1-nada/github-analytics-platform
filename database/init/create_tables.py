import logging
from pathlib import Path

from database.init.db import create_connection

logger = logging.getLogger(__name__)


def create_tables():

    conn = create_connection()
    cursor = conn.cursor()

    schemas_dir = Path(__file__).parent.parent / "schemas"

    files = [
        schemas_dir / "repositories.sql",
        schemas_dir / "commits.sql",
        schemas_dir / "issues.sql",
        schemas_dir / "pull_requests.sql",
        schemas_dir / "commit_activity.sql",
        schemas_dir / "contributors.sql",
    ]

    try:
        for sql_file in files:
            logger.info("Creating table from %s", sql_file.name)

            sql = sql_file.read_text()
            cursor.execute(sql)

        conn.commit()

        logger.info("All tables created successfully")

    except Exception:
        conn.rollback()
        logger.exception("Failed to create tables")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    create_tables()
