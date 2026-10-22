import psycopg2

from config import get_settings


def create_connection():
    settings = get_settings()
    settings.require_database_settings()
    return psycopg2.connect(
        host=settings.pg_host,
        database=settings.pg_database,
        user=settings.pg_user,
        password=settings.pg_password,
        port=settings.pg_port,
    )
