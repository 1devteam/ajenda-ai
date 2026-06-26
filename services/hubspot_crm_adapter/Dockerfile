FROM python:3.12-slim

WORKDIR /app

COPY services/hubspot_crm_adapter/requirements.txt /tmp/hubspot-crm-adapter-requirements.txt
RUN pip install --no-cache-dir -r /tmp/hubspot-crm-adapter-requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/hubspot_crm_adapter /app/services/hubspot_crm_adapter

ENV PYTHONPATH=/app
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "services.hubspot_crm_adapter.main:app", "--host", "0.0.0.0", "--port", "8080"]