# Production API image — canonical build path shared by dev Compose, CI, and release.
# Worker and migrate images live under deploy/docker/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY backend /app/backend
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY deploy/scripts /app/deploy/scripts

RUN pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
    && pip install --no-cache-dir . \
    && pip uninstall --yes pip setuptools \
    && rm -rf /root/.cache/pip /tmp/pip-*

EXPOSE 8000

ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]
