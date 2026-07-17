"""CMMS (Computerized Maintenance Management System) adapter abstraction.

A :class:`CmmsAdapter` is the single seam through which the platform talks to a
maintenance system of record (Maximo, SAP PM, Fiix, eMaint, ...). The default,
built-in adapter is **strictly read-only**: it can *pull* work orders and asset
maintenance history for context, and nothing else.

A write-back adapter may exist behind an explicit config flag
(``CMMS_WRITE_BACK_ENABLED``), but it is bound by two non-negotiable rules:

1. **Operator approval first.** A CMMS ticket is only ever created for a work
   order the operator has *approved*; :meth:`CmmsAdapter.create_work_order`
   rejects an unapproved work order.
2. **A ticket is not a device command.** Writing back creates a CMMS *ticket*
   (a business-system record) only. It is emphatically **NOT** an OT/control
   path: it never commands a PLC / SCADA / VFD / valve / pump / dosing system,
   and it never sets ``control_write_enabled``. The platform's advisory-only
   control boundary is entirely independent of, and unaffected by, CMMS
   write-back.

The read-only posture of the default adapter is enforced by a test that scans
this package for forbidden control-write markers (mirroring the platform's
control-write boundary guard).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from canonical_water_model import AssetMaintenanceRecord, MaintenanceWorkOrder


class CmmsError(RuntimeError):
    """Base error for CMMS adapter failures."""


class CmmsWriteNotEnabled(CmmsError):
    """Raised when a write-back is attempted on a read-only adapter.

    Also raised (as a guard) if a write-back is attempted for a work order that
    has not been approved by an operator, or if a caller ever tries to route a
    control action through the CMMS -- a CMMS ticket is never a control command.
    """


class CmmsAdapter(ABC):
    """Read-only-by-default CMMS adapter interface.

    Concrete adapters map their underlying CMMS onto the canonical
    :class:`~canonical_water_model.MaintenanceWorkOrder` /
    :class:`~canonical_water_model.AssetMaintenanceRecord` models.
    """

    #: Machine kind, e.g. "synthetic" | "maximo" | "sap-pm".
    kind: str = "abstract"
    #: Human-readable instance name.
    name: str = "abstract"
    #: Whether this adapter can write a ticket BACK to the CMMS. Even when
    #: ``True`` a write is a business-system ticket ONLY (never an OT/control
    #: path) and only performed after operator approval. Default: read-only.
    write_enabled: bool = False

    @abstractmethod
    def pull_work_orders(self) -> list[MaintenanceWorkOrder]:
        """Pull the current work orders from the CMMS (read-only)."""
        raise NotImplementedError

    @abstractmethod
    def pull_asset_history(self, asset_id: str) -> list[AssetMaintenanceRecord]:
        """Pull an asset's historical maintenance records (read-only)."""
        raise NotImplementedError

    def create_work_order(
        self, work_order: MaintenanceWorkOrder, *, approved: bool
    ) -> MaintenanceWorkOrder:
        """Write an approved work order back to the CMMS as a ticket.

        The default implementation is READ-ONLY and refuses: it raises
        :class:`CmmsWriteNotEnabled`. A write-back adapter overrides this, but
        must still require ``approved is True`` and must only ever create a CMMS
        ticket -- never a control/OT command.
        """
        raise CmmsWriteNotEnabled(
            f"CMMS adapter {self.name!r} is read-only; write-back is disabled "
            "(set CMMS_WRITE_BACK_ENABLED=true to enable business-system ticket "
            "creation for operator-approved work orders only -- never a control path)"
        )

    def describe(self) -> dict:
        """A small, safe description of the adapter for status endpoints."""
        return {
            "kind": self.kind,
            "name": self.name,
            "write_enabled": self.write_enabled,
            "read_only": not self.write_enabled,
            # Make the boundary explicit for any consumer: even a write-back is
            # a CMMS ticket, never an OT/control command.
            "write_back_is_control_path": False,
            "operator_approval_required": True,
        }
