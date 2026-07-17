# edge-gateway: outbound-only, read-only OT edge collector (no inbound server).
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
