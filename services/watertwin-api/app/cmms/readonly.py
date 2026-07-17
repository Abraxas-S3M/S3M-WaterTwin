"""Read-only default CMMS adapter (synthetic system of record).

The built-in adapter models a small synthetic CMMS: it exposes a handful of open
work orders and a per-asset maintenance history so the Maintenance Center has
realistic context to display. It has **no write path** -- ``create_work_order``
is inherited from :class:`~app.cmms.base.CmmsAdapter` and refuses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from canonical_water_model import (
    AssetMaintenanceRecord,
    ControlBoundary,
    DataProvenance,
    MaintenanceWorkOrder,
    WorkOrderPriority,
    WorkOrderSource,
    WorkOrderStatus,
)

from .base import CmmsAdapter

DEFAULT_CMMS_SYSTEM = "synthetic-cmms"


def _days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class ReadOnlyCmmsAdapter(CmmsAdapter):
    """A strictly read-only, synthetic CMMS adapter (the default).

    Pulls a small set of synthetic open work orders and per-asset maintenance
    history. ``write_enabled`` is ``False`` and ``create_work_order`` refuses.
    """

    kind = "synthetic"
    write_enabled = False

    def __init__(self, system_name: str = DEFAULT_CMMS_SYSTEM) -> None:
        self.name = system_name

    def pull_work_orders(self) -> list[MaintenanceWorkOrder]:
        cb = ControlBoundary()
        return [
            MaintenanceWorkOrder(
                work_order_id="CMMS-1042",
                asset_id="AST-CF-01",
                asset_name="Cartridge Filter Bank",
                title="Replace 5 µm cartridge filter set",
                description=(
                    "Scheduled cartridge replacement pulled from the CMMS of "
                    "record (read-only). Differential pressure trending up."
                ),
                priority=WorkOrderPriority.medium,
                status=WorkOrderStatus.open,
                source=WorkOrderSource.cmms,
                cmms_system=self.name,
                cmms_external_id="CMMS-1042",
                control_boundary=cb,
                provenance=DataProvenance.synthetic,
                created_at=_days_ago(3),
            ),
            MaintenanceWorkOrder(
                work_order_id="CMMS-1039",
                asset_id="AST-ERD-01",
                asset_name="Energy Recovery Device",
                title="Inspect ERD rotor seal",
                description=(
                    "Preventive inspection of the energy-recovery device rotor "
                    "seal (read-only CMMS record)."
                ),
                priority=WorkOrderPriority.low,
                status=WorkOrderStatus.in_progress,
                source=WorkOrderSource.cmms,
                cmms_system=self.name,
                cmms_external_id="CMMS-1039",
                control_boundary=cb,
                provenance=DataProvenance.synthetic,
                created_at=_days_ago(6),
            ),
        ]

    def pull_asset_history(self, asset_id: str) -> list[AssetMaintenanceRecord]:
        history: dict[str, list[AssetMaintenanceRecord]] = {
            "AST-HPP-01": [
                AssetMaintenanceRecord(
                    work_order_id="CMMS-0912",
                    asset_id="AST-HPP-01",
                    title="Drive-end bearing replacement",
                    status=WorkOrderStatus.completed,
                    performed_at=_days_ago(220),
                    performed_by="mechanical-crew",
                    labor_hours=9.5,
                    cost=26000.0,
                    notes="Bearings replaced; vibration returned to baseline.",
                    cmms_system=self.name,
                ),
                AssetMaintenanceRecord(
                    work_order_id="CMMS-0788",
                    asset_id="AST-HPP-01",
                    title="Mechanical seal replacement",
                    status=WorkOrderStatus.completed,
                    performed_at=_days_ago(430),
                    performed_by="mechanical-crew",
                    labor_hours=6.0,
                    cost=8200.0,
                    notes="Seal leakage resolved.",
                    cmms_system=self.name,
                ),
            ],
            "AST-MEMB-01": [
                AssetMaintenanceRecord(
                    work_order_id="CMMS-0865",
                    asset_id="AST-MEMB-01",
                    title="Clean-in-place (CIP) — alkaline + acid cycle",
                    status=WorkOrderStatus.completed,
                    performed_at=_days_ago(120),
                    performed_by="process-crew",
                    labor_hours=14.0,
                    cost=9800.0,
                    notes="Normalized dP recovered ~60% of the fouling penalty.",
                    cmms_system=self.name,
                ),
            ],
        }
        return history.get(asset_id, [])
