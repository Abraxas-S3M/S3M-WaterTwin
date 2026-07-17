"""Pluggable CMMS adapters (read-only by default).

The active adapter is resolved from configuration. The default is the built-in,
strictly read-only :class:`ReadOnlyCmmsAdapter` (pull work orders / asset
history only). A :class:`WriteBackCmmsAdapter` -- which can create a CMMS
*ticket* for an operator-approved work order -- is selected only when
``CMMS_WRITE_BACK_ENABLED=true``.

No adapter in this package writes to a control system. A CMMS write-back is a
business-system ticket, never an OT/control command, and only ever happens after
operator approval. This boundary is documented on :class:`CmmsAdapter` and
enforced by a boundary-guard test.
"""

from __future__ import annotations

import logging

from .base import CmmsAdapter, CmmsError, CmmsWriteNotEnabled
from .readonly import DEFAULT_CMMS_SYSTEM, ReadOnlyCmmsAdapter
from .writeback import WriteBackCmmsAdapter

logger = logging.getLogger("watertwin.cmms")

__all__ = [
    "CmmsAdapter",
    "CmmsError",
    "CmmsWriteNotEnabled",
    "ReadOnlyCmmsAdapter",
    "WriteBackCmmsAdapter",
    "DEFAULT_CMMS_SYSTEM",
    "resolve_cmms_adapter",
]


def resolve_cmms_adapter(config) -> CmmsAdapter:
    """Resolve the active CMMS adapter from config.

    Read-only by default. When ``CMMS_WRITE_BACK_ENABLED`` is true a write-back
    adapter is returned; even then it only creates CMMS tickets for
    operator-approved work orders and never a control path.
    """
    system_name = getattr(config, "CMMS_SYSTEM_NAME", None) or DEFAULT_CMMS_SYSTEM
    if getattr(config, "CMMS_WRITE_BACK_ENABLED", False):
        logger.warning(
            "CMMS write-back ENABLED: operator-approved work orders may be "
            "written to %r as tickets. This is a business-system ticket path, "
            "NOT a control/OT path.",
            system_name,
        )
        return WriteBackCmmsAdapter(system_name)
    logger.info("CMMS adapter: read-only (%s)", system_name)
    return ReadOnlyCmmsAdapter(system_name)
