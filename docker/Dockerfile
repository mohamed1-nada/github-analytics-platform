# Airflow image extended with the pipeline's own dependencies.
#
# Requirements are exported from uv.lock so the image stays bit-for-bit in
# sync with the local .venv:
#   uv export --frozen --no-dev --no-emit-project --no-hashes \
#       --output-file docker/requirements.txt
#
# Re-run that command (and `docker compose build`) whenever dependencies in
# pyproject.toml change. Source code is NOT baked in: the repo is bind-mounted
# at /opt/lap by docker-compose, so DAG and pipeline edits need no rebuild.
ARG AIRFLOW_IMAGE=apache/airflow:3.3.2-python3.14
FROM ${AIRFLOW_IMAGE}

# Pinning apache-airflow to the version already in the image guarantees pip
# never upgrades/downgrades Airflow while resolving the extra requirements
# (official recommendation, see "Using custom images" in the Airflow docs).
ARG AIRFLOW_VERSION=3.3.2

COPY requirements.txt /tmp/lap-requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" \
        -r /tmp/lap-requirements.txt
