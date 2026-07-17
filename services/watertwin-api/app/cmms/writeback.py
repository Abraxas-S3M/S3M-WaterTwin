"""Optional write-back CMMS adapter (behind a config flag).

This adapter demonstrates the *only* supported write path from the platform: it
creates a CMMS **ticket** for an operator-approved work order. It is enabled
exclusively via ``CMMS_WRITE_BACK_ENABLED=true``.

Boundary (non-negotiable):

* **Approval gate.** :meth:`create_work_order` refuses unless the work order was
  approved by an operator (``approved is True``). It never fabricates approval.
* **Not a control path.** Creating a ticket is a business-system write only. It
  sets the ``cmms_*`` fields on the work order and NOTHING else. It never
  commands any OT/control device and it never touches ``control_boundary`` /
  ``control_write_enabled`` -- those remain advisory / read-only. A work order
  is a ticket, not a device command.

The synthetic implementation records tickets in memory; a real deployment would
POST to the CMMS REST API here (still a ticket, still gated on approval, still
never a control path).
"""

from __future__ import annotations

from canonical_water_model import (
    ApprovalStatus,
    CmmsSyncStatus,
    MaintenanceWorkOrder,
    WorkOrderStatus,
    now_iso,
)

from .base import CmmsWriteNotEnabled
from .readonly import DEFAULT_CMMS_SYSTEM, ReadOnlyCmmsAdapter


class WriteBackCmmsAdapter(ReadOnlyCmmsAdapter):
    """A CMMS adapter that can create tickets for operator-approved work orders.

    Inherits the read-only pull methods; adds a strictly gated, ticket-only
    write path. Enabled only when ``CMMS_WRITE_BACK_ENABLED=true``.
    """

    write_enabled = True

    def __init__(self, system_name: str = DEFAULT_CMMS_SYSTEM) -> None:
        super().__init__(system_name)
        self._ticket_seq = 5000
        self._tickets: dict[str, MaintenanceWorkOrder] = {}

    def create_work_order(
        self, work_order: MaintenanceWorkOrder, *, approved: bool
    ) -> MaintenanceWorkOrder:
        # Approval gate: never create a ticket for an unapproved work order.
        if not approved or work_order.approval_status != ApprovalStatus.approved:
            raise CmmsWriteNotEnabled(
                "refusing to create a CMMS ticket for a work order that has not "
                "been approved by an operator"
            )

        self._ticket_seq += 1
        external_id = f"{self.name.upper()}-{self._ticket_seq}"

        # A ticket is a business-system record ONLY. We copy the work order,
        # stamp the CMMS linkage, and mark it synced/open. Crucially we do NOT
        # modify control_boundary: this is not, and can never be, a control path.
        ticket = work_order.model_copy(
            update={
                "cmms_system": self.name,
                "cmms_external_id": external_id,
                "cmms_sync_status": CmmsSyncStatus.synced,
                "status": WorkOrderStatus.open,
                "decided_at": work_order.decided_at or now_iso(),
            }
        )
        self._tickets[external_id] = ticket
        return ticket
