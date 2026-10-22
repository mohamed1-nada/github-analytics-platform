from config import Settings


def test_database_port_ignores_generic_port(monkeypatch):
    """`PORT` belongs to web servers; it must not redirect the database."""
    monkeypatch.delenv("PGPORT", raising=False)
    monkeypatch.delenv("DBPORT", raising=False)
    monkeypatch.setenv("PORT", "9999")

    assert Settings().pg_port == "5432"


def test_database_port_reads_pgport(monkeypatch):
    monkeypatch.setenv("PGPORT", "5433")

    assert Settings().pg_port == "5433"


def test_require_database_settings_lists_missing(monkeypatch):
    for name in (
        "PGDATABASE",
        "DATABASE_NAME",
        "PGUSER",
        "DBUSER",
        "PGPASSWORD",
        "DBPASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    try:
        settings.require_database_settings()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as error:
        assert "PGDATABASE" in str(error)
        assert ".env.example" in str(error)
