"""edge-gateway entrypoint: an outbound-only collection worker (no server).

This process runs a plain collection loop. It deliberately does NOT start any
web server or bind any listening socket -- the gateway's only network activity
is the outbound push to the watertwin-api ingest endpoint. Run it directly:

    python -m app.main
"""

from __future__ import annotations

import logging
import signal
import threading

from . import config
from .buffer import EncryptedBuffer
from .collector import Collector
from .forwarder import HttpForwarder
from .health import SourceHealth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("edge_gateway.main")


def build_collector() -> Collector:
    """Construct the collector graph from the module config."""
    buffer = EncryptedBuffer(
        config.BUFFER_PATH,
        key=config.BUFFER_KEY,
        max_rows=config.BUFFER_MAX_ROWS,
    )
    forwarder = HttpForwarder(
        base_url=config.API_BASE_URL,
        ingest_path=config.INGEST_PATH,
        gateway_id=config.GATEWAY_ID,
        token=config.API_TOKEN,
        timeout=config.HTTP_TIMEOUT_S,
    )
    health = SourceHealth(gateway_id=config.GATEWAY_ID)
    return Collector(config, buffer, forwarder, health=health)


def main() -> None:
    logger.info(
        "starting %s v%s (gateway_id=%s, source=%s, target=%s%s)",
        config.SERVICE_NAME,
        config.SERVICE_VERSION,
        config.GATEWAY_ID,
        config.OT_SOURCE,
        config.API_BASE_URL,
        config.INGEST_PATH,
    )
    collector = build_collector()
    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("received signal %s; shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    collector.run_forever(stop_event)


if __name__ == "__main__":
    main()
