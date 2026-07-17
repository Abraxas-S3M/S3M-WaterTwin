"""Usage metering for billing export.

Commercial-hardening work package: **usage metering**. This tracks the
billable dimensions of platform usage — distinct **facilities**, distinct
**assets** under management, and **ingest volume** (telemetry readings brought
in through the read-only ingestion path) — plus a lightweight per-category API
call count for operational visibility. A billing export renders those counters
against the tenant's plan limits.

Design notes:

* Metering is **advisory bookkeeping only**. Counting usage never writes to a
  control system and never touches the safety boundary.
* Counters are aggregated in memory (thread-safe) and are authoritative for the
  current billing **period** (calendar month, UTC). A production deployment
  would additionally flush period snapshots to TimescaleDB; that persistence is
  out of scope here and the in-memory meter is the source of truth for the
  export.
* The meter is reset by the demo ``/api/v1/reset`` convenience alongside the
  audit/recommendation stores.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import UTC, datetime


def _current_period() -> str:
    """Billing period key: ``YYYY-MM`` in UTC."""
    return datetime.now(UTC).strftime("%Y-%m")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class UsageMeter:
    """Thread-safe in-memory usage meter for the active billing period."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._period = _current_period()
        self._facilities: set[str] = set()
        self._assets: set[str] = set()
        self._ingest_events = 0
        self._api_calls: dict[str, int] = defaultdict(int)

    # -- recording ------------------------------------------------------------

    def _roll_period_if_needed(self) -> None:
        """Reset counters when the calendar month rolls over (UTC)."""
        now = _current_period()
        if now != self._period:
            self._period = now
            self._facilities.clear()
            self._assets.clear()
            self._ingest_events = 0
            self._api_calls.clear()

    def record_facility(self, facility_id: str | None) -> None:
        if not facility_id:
            return
        with self._lock:
            self._roll_period_if_needed()
            self._facilities.add(str(facility_id))

    def record_asset(self, asset_id: str | None) -> None:
        if not asset_id:
            return
        with self._lock:
            self._roll_period_if_needed()
            self._assets.add(str(asset_id))

    def record_ingest(self, count: int = 1) -> None:
        """Record ``count`` ingested telemetry readings (ingest volume)."""
        if count <= 0:
            return
        with self._lock:
            self._roll_period_if_needed()
            self._ingest_events += int(count)

    def record_api_call(self, category: str) -> None:
        with self._lock:
            self._roll_period_if_needed()
            self._api_calls[category] += 1

    # -- reporting ------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return the current period's usage counts."""
        with self._lock:
            self._roll_period_if_needed()
            return {
                "period": self._period,
                "facilities": len(self._facilities),
                "assets": len(self._assets),
                "ingest_events": self._ingest_events,
                "api_calls": dict(self._api_calls),
                "facility_ids": sorted(self._facilities),
                "asset_ids": sorted(self._assets),
            }

    def billing_export(
        self,
        *,
        tenant_id: str,
        plan: str,
        limits: dict[str, int] | None = None,
    ) -> dict:
        """Render a billing export for the current period.

        Each metered dimension is reported with its quantity and (when the plan
        defines one) the plan limit and whether usage is within it. Exceeding a
        limit is a billing signal only; it never changes any safety property.
        """
        snap = self.snapshot()
        limits = limits or {}

        def _row(metric: str, quantity: int, unit: str, limit_key: str) -> dict:
            limit = limits.get(limit_key, -1)
            return {
                "metric": metric,
                "quantity": quantity,
                "unit": unit,
                "limit": limit,
                "unlimited": limit == -1,
                "within_limit": limit == -1 or quantity <= limit,
            }

        return {
            "tenant_id": tenant_id,
            "plan": plan,
            "period": snap["period"],
            "generated_at": _utcnow_iso(),
            "metrics": [
                _row("facilities", snap["facilities"], "facility", "max_facilities"),
                _row("assets", snap["assets"], "asset", "max_assets"),
                _row(
                    "ingest_events",
                    snap["ingest_events"],
                    "reading",
                    "max_monthly_ingest_events",
                ),
            ],
            "api_calls": snap["api_calls"],
        }

    def reset(self) -> None:
        with self._lock:
            self._period = _current_period()
            self._facilities.clear()
            self._assets.clear()
            self._ingest_events = 0
            self._api_calls.clear()


# Process-wide meter instance (mirrors the module-level store/reco_store).
meter = UsageMeter()


__all__ = ["UsageMeter", "meter"]
