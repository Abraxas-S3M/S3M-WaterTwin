"""HTTP API for S3M-WaterTwin.

The API is read-only and advisory. It exposes health, the safety envelope, and
an endpoint that computes preliminary analytics from a synthetic telemetry
packet. It exposes no route that could command physical equipment.
"""

from __future__ import annotations

from watertwin.api.app import create_app

__all__ = ["create_app"]
