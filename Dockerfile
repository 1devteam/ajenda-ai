FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY backend /app/backend
COPY alembic.ini /app/
COPY alembic /app/alembic

RUN pip install --upgrade pip \
    && pip install --no-cache-dir . \
    && rm -rf /root/.cache/pip

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
