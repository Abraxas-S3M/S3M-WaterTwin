"""Shared job store for async simulation jobs.

Follows the shared store pattern: a small, swappable persistence interface. The
default implementation is a JSON-file-backed store guarded by a lock, which is
adequate for a single-container service and keeps job state across restarts.
The same :class:`JobStore` interface can later be backed by Redis/Postgres.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from simulation_contracts import SimulationJob


class JobStore:
    """Thread-safe, file-backed store of :class:`SimulationJob` records."""

    def __init__(self, path: str) -> None:
        self._path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._jobs: dict[str, SimulationJob] = {}
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return
        for job_id, data in raw.items():
            try:
                self._jobs[job_id] = SimulationJob.model_validate(data)
            except Exception:
                continue

    def _flush(self) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({jid: j.model_dump(mode="json") for jid, j in self._jobs.items()}, fh, indent=2)
        os.replace(tmp, self._path)

    def put(self, job: SimulationJob) -> SimulationJob:
        with self._lock:
            job.touch()
            self._jobs[job.job_id] = job
            self._flush()
            return job

    def get(self, job_id: str) -> Optional[SimulationJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[SimulationJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._flush()
