"""Client used by watertwin-api to talk to the treatment-sim service.

Submits async simulation jobs, polls them to completion, and returns the parsed
result. Simulation output is always ``provenance="simulated"`` /
``status="preliminary"``; the API is responsible for surfacing that to the
operator and never treating it as measured or validated.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://treatment-sim:8080"


class TreatmentSimError(RuntimeError):
    """Raised when a simulation job fails or times out."""


class TreatmentSimClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.25,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            return resp.json()

    async def _run_job(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            job = resp.json()
            job_id = job["job_id"]

            deadline = asyncio.get_event_loop().time() + self.timeout_s
            while True:
                poll = await client.get(f"/api/v1/process/jobs/{job_id}")
                poll.raise_for_status()
                job = poll.json()
                if job["state"] == "succeeded":
                    return job
                if job["state"] == "failed":
                    raise TreatmentSimError(job.get("error") or "simulation failed")
                if asyncio.get_event_loop().time() > deadline:
                    raise TreatmentSimError(f"job {job_id} timed out")
                await asyncio.sleep(self.poll_interval_s)

    async def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run_job("/api/v1/process/simulate", payload)

    async def optimize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run_job("/api/v1/process/optimize", payload)

    async def sensitivity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run_job("/api/v1/process/sensitivity", payload)

    async def membrane_degradation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run_job(
            "/api/v1/process/membrane-degradation", payload
        )
