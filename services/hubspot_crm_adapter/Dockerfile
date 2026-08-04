FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/ajenda \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 ajenda \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/ajenda --shell /usr/sbin/nologin ajenda

COPY services/hubspot_crm_adapter/requirements.txt /tmp/hubspot-crm-adapter-requirements.txt
RUN pip install --no-cache-dir -r /tmp/hubspot-crm-adapter-requirements.txt \
    && pip uninstall --yes pip setuptools \
    && rm -rf /root/.cache/pip /tmp/pip-* /tmp/hubspot-crm-adapter-requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/hubspot_crm_adapter /app/services/hubspot_crm_adapter

RUN chown -R ajenda:ajenda /app /home/ajenda

USER 1000

EXPOSE 8080

CMD ["uvicorn", "services.hubspot_crm_adapter.main:app", "--host", "0.0.0.0", "--port", "8080"]
