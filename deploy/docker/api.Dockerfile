# API image — must stay hardening-parity with the root Dockerfile.
# Prefer the root Dockerfile for CI/release; this path remains for Compose consumers.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY backend ./backend

RUN pip install --upgrade "pip<26.0.1" "setuptools>=78.1.1" wheel \
    && pip install --prefix=/install .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/ajenda \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 ajenda \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/ajenda --shell /usr/sbin/nologin ajenda

COPY --from=builder /install /usr/local
COPY pyproject.toml README.md /app/
COPY backend /app/backend
COPY alembic.ini /app/
COPY alembic /app/alembic
COPY deploy/scripts /app/deploy/scripts
COPY docs/product/autonomy-disclaimer-catalog.v1.yaml /app/docs/product/autonomy-disclaimer-catalog.v1.yaml

RUN chown -R ajenda:ajenda /app /home/ajenda

USER 1000

EXPOSE 8000

ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]
