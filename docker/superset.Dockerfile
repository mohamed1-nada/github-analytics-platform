# Superset image with the PostgreSQL driver installed.
#
# The official `apache/superset:6.1.0` image ships without a Postgres
# driver, so `SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://...` fails with
# "No module named 'psycopg2'". Everything else is taken from the upstream
# image; only the driver is added, into the image's own virtualenv.
#
# `uv` is already present in the image and is what created that virtualenv,
# so it is used here too.
FROM apache/superset:6.1.0

USER root

RUN uv pip install --python /app/.venv/bin/python --no-cache \
        "psycopg2-binary>=2.9.9" \
    && /app/.venv/bin/python -c "import psycopg2; print('psycopg2', psycopg2.__version__)"

# The container runs as the unprivileged `superset` user (uid 1000) and
# SUPERSET_HOME points here, so the directories Superset writes to — uploads,
# data, screenshots and the celery beat schedule — have to be writable by it.
RUN mkdir -p /app/superset_home/uploads \
             /app/superset_home/data \
             /app/superset_home/screenshots \
    && chmod -R 777 /app/superset_home

USER superset
