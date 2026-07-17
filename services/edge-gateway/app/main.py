"""edge-gateway service: durable store-and-forward telemetry forwarder.

Exposes a tiny operational surface (``/health`` and ``/stats``) and runs the
producer + forwarder loops in the background (see :mod:`app.forwarder`). The
gateway is strictly read-only with respect to plant control: it reads/synthesizes
telemetry and forwards it upstream; it never writes to any control system.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config
from .forwarder import Gateway

gateway = Gateway()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    gateway.start()
    try:
        yield
    finally:
        gateway.stop()


app = FastAPI(
    title="S3M-WaterTwin edge-gateway",
    version=config.SERVICE_VERSION,
    description="Read-only telemetry store-and-forward edge gateway.",
    lifespan=_lifespan,
)


@app.get("/health")
def health() -> dict:
    return gateway.health()


@app.get("/stats")
def stats() -> dict:
    return gateway.health()
