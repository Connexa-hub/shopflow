FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY packages/configuration /packages/configuration
COPY packages/constants /packages/constants
COPY packages/database /packages/database
RUN pip install /packages/configuration /packages/constants /packages/database

COPY services/payment-service/pyproject.toml ./
RUN pip install ".[dev]" || pip install .

COPY services/payment-service/app ./app
COPY services/payment-service/alembic ./alembic
COPY services/payment-service/alembic.ini ./alembic.ini

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
