FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY backend /app/backend
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY deploy/scripts /app/deploy/scripts

RUN pip install --upgrade pip && pip install .

ENTRYPOINT ["/app/deploy/scripts/run-migrations.sh"]
