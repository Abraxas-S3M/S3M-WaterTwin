# edge-gateway: outbound-only, read-only OT edge collector (no inbound server).
# edge-gateway: read-only telemetry store-and-forward edge gateway.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/packages \
    EDGE_GATEWAY_BUFFER_PATH=/data/edge-buffer.db \
    EDGE_GATEWAY_HEARTBEAT_PATH=/data/edge-gateway.heartbeat

WORKDIR /app

COPY services/edge-gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Shared packages (canonical model + read-only OT sources + tag normalization)
# and the gateway service code.
COPY packages/ ./packages/
COPY services/edge-gateway/ ./

# Persist the encrypted store-and-forward buffer across restarts.
VOLUME ["/data"]

# The gateway binds NO inbound port; liveness is a heartbeat-file freshness check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.main"]
    PYTHONPATH=/app/packages

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/edge-gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/ ./packages/
COPY services/edge-gateway/ ./

EXPOSE 8200

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -fsS http://localhost:8200/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
