FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY waagent ./waagent
RUN pip install --no-cache-dir .

# Cloud Run injects PORT. The same image serves the webhook and the worker service;
# they differ only in env vars and ingress settings.
CMD ["sh", "-c", "uvicorn 'waagent.main:create_app' --factory --host 0.0.0.0 --port ${PORT:-8080}"]
