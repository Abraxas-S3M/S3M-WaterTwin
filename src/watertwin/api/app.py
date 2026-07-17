"""FastAPI application factory for S3M-WaterTwin.

Builds the read-only, advisory service and customises its OpenAPI document to
state the safety posture prominently. A response-header middleware stamps every
response with the advisory control mode so intermediaries and clients can verify
it without parsing bodies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from watertwin import __version__
from watertwin.api.routes import router
from watertwin.logging_config import configure_logging, get_logger
from watertwin.safety import (
    CONTROL_MODE,
    CONTROL_WRITE_ENABLED,
    OPERATOR_APPROVAL_REQUIRED,
    assert_advisory_only,
)

logger = get_logger("app")

_API_DESCRIPTION = """\
Read-only, advisory digital twin for a single seawater reverse-osmosis (RO)
treatment train.

**Safety boundary (enforced):** `control_mode = "advisory"`,
`operator_approval_required = true`, `control_write_enabled = false`. There is no
control-write code path; this service cannot command a PLC, SCADA, VFD, valve,
pump, or dosing system.

**Truthfulness:** all telemetry is synthetic (`provenance = "synthetic"`) and all
analytics are preliminary (`status = "preliminary"`). Output is never a validated
production prediction, guaranteed saving, compliance certification, or autonomous
control action.
"""


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    The advisory-only safety boundary is asserted at construction time; if it
    were ever violated, the app would fail fast rather than start in an unsafe
    state.
    """

    configure_logging()
    assert_advisory_only()

    app = FastAPI(
        title="S3M-WaterTwin",
        version=__version__,
        description=_API_DESCRIPTION,
        summary="Advisory, read-only seawater RO digital twin.",
        contact={"name": "Abraxas-S3M"},
        license_info={"name": "Apache-2.0"},
    )

    @app.middleware("http")
    async def add_advisory_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Control-Mode"] = CONTROL_MODE
        response.headers["X-Operator-Approval-Required"] = str(OPERATOR_APPROVAL_REQUIRED).lower()
        response.headers["X-Control-Write-Enabled"] = str(CONTROL_WRITE_ENABLED).lower()
        return response

    app.include_router(router)

    logger.info(
        "S3M-WaterTwin API initialised.",
        extra={"version": __version__, "control_mode": CONTROL_MODE},
    )
    return app


app = create_app()
