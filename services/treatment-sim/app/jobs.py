"""In-memory async job store for simulation runs.

Simulations are submitted as async jobs: the endpoint returns a ``queued`` job
immediately and the solve runs in a worker thread (so a slow WaterTAP solve does
not block the event loop). Results are polled via ``GET .../jobs/{job_id}``.

The store is intentionally in-memory: simulation output is preliminary,
read-only what-if data and is not a system of record.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Awaitable, Callable

from pydantic import BaseModel
from simulation_contracts import JobState, SimulationJob, SimulationKind, now_iso

logger = logging.getLogger("treatment-sim.jobs")

Runner = Callable[[], BaseModel]


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, SimulationJob] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        kind: SimulationKind,
        request: dict,
        scenario_id: str | None,
    ) -> SimulationJob:
        job = SimulationJob(
            job_id=str(uuid.uuid4()),
            kind=kind,
            request=request,
            scenario_id=scenario_id,
        )
        async with self._lock:
            self._jobs[job.job_id] = job
        return job

    async def get(self, job_id: str) -> SimulationJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def _update(self, job_id: str, **changes) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            updated = job.model_copy(update={**changes, "updated_at": now_iso()})
            self._jobs[job_id] = updated

    def submit(self, job: SimulationJob, runner: Runner) -> None:
        """Schedule ``runner`` to execute the job in a worker thread."""
        asyncio.create_task(self._run(job.job_id, runner))

    async def _run(self, job_id: str, runner: Runner) -> None:
        await self._update(job_id, state=JobState.running)
        loop = asyncio.get_running_loop()
        try:
            result: BaseModel = await loop.run_in_executor(None, runner)
            engine = getattr(result, "engine", None)
            await self._update(
                job_id,
                state=JobState.succeeded,
                result=result.model_dump(mode="json"),
                engine=engine,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job %s failed", job_id)
            await self._update(job_id, state=JobState.failed, error=str(exc))


store = JobStore()
