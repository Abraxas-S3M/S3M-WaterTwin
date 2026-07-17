"""Client for the hydraulic-sim service.

Submits an async scenario job, polls until it completes, and returns the parsed
:class:`SimulationResult`. The client accepts any session object exposing
``.post(path, json=...)`` and ``.get(path)`` returning objects with
``.status_code`` and ``.json()`` — satisfied by both ``httpx.Client`` (real
deployment) and Starlette's ``TestClient`` (in-process integration tests).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from simulation_contracts import ScenarioType, SimulationResult

_SCENARIO_PATHS = {
    ScenarioType.baseline: "/api/v1/hydraulics/simulate",
    ScenarioType.pump_outage: "/api/v1/hydraulics/pump-outage",
    ScenarioType.valve_closure: "/api/v1/hydraulics/valve-closure",
    ScenarioType.demand_change: "/api/v1/hydraulics/demand-change",
    ScenarioType.leak: "/api/v1/hydraulics/leak",
}

_TERMINAL = {"completed", "failed"}


class HydraulicSimError(RuntimeError):
    pass


class HydraulicSimClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        session: Any = None,
        poll_attempts: int = 100,
        poll_interval: float = 0.05,
    ) -> None:
        if session is None:
            import httpx

            session = httpx.Client(base_url=base_url, timeout=60.0)
        self._session = session
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval

    def health(self) -> dict:
        resp = self._session.get("/health")
        if resp.status_code != 200:
            raise HydraulicSimError(f"hydraulic-sim health {resp.status_code}")
        return resp.json()

    def network_info(self) -> dict:
        return self._session.get("/api/v1/hydraulics/network").json()

    def run(
        self,
        scenario: ScenarioType,
        parameters: Optional[dict[str, Any]] = None,
        facility_id: str = "S3M-DESAL-01",
        train_id: str = "RO-TRAIN-001",
        requested_by: Optional[str] = None,
    ) -> SimulationResult:
        path = _SCENARIO_PATHS[scenario]
        payload = {
            "scenario": scenario.value,
            "facility_id": facility_id,
            "train_id": train_id,
            "parameters": parameters or {},
            "requested_by": requested_by,
        }
        resp = self._session.post(path, json=payload)
        if resp.status_code != 202:
            raise HydraulicSimError(
                f"submit {scenario.value} failed: {resp.status_code} {resp.text}"
            )
        job_id = resp.json()["job_id"]
        return self._await_result(job_id)

    def _await_result(self, job_id: str) -> SimulationResult:
        for _ in range(self._poll_attempts):
            resp = self._session.get(f"/api/v1/hydraulics/jobs/{job_id}")
            if resp.status_code != 200:
                raise HydraulicSimError(f"job poll {job_id}: {resp.status_code}")
            job = resp.json()
            state = job.get("state")
            if state in _TERMINAL:
                if state == "failed":
                    raise HydraulicSimError(f"job {job_id} failed: {job.get('error')}")
                return SimulationResult.model_validate(job["result"])
            time.sleep(self._poll_interval)
        raise HydraulicSimError(f"job {job_id} did not complete in time")
