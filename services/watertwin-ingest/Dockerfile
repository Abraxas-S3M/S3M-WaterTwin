# watertwin-ingest: immutable customer-file intake (receive, store, scan, track).
#
# Optional, independently deployable. It has NO direct database connection to
# the canonical store (it talks to watertwin-api over HTTP) and NO OT network
# access. With this container stopped the rest of the platform still works.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/packages \
    INGEST_STORAGE_ROOT=/data/ingest

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/watertwin-ingest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Shared packages (canonical model, advisory event bus, observability) and the
# ingest service code.
COPY packages/ ./packages/
COPY services/watertwin-ingest/ ./

# Persist the write-once content store across restarts.
VOLUME ["/data"]

EXPOSE 8300

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -fsS http://localhost:8300/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]
