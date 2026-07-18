"""watertwin-ingest: sandboxed customer-file ingestion for the water twin.

This service accepts a customer-supplied engineering file (Phase C: EPANET 2.2
``.inp`` network models), parses it inside a hardened sandbox worker, reconciles
the parsed entities against the *current canonical configuration* (fetched from
``watertwin-api`` over HTTP — never a direct database read), and produces a
field-level :class:`~app.proposal.ChangeProposal` for human review.

Safety posture (unchanged by this service):

* It is strictly **read-only** with respect to the canonical model and to OT.
  Nothing here writes to the canonical config, and there is no SCADA/PLC/OPC UA/
  MQTT code path anywhere in the service.
* Parsing is *advisory*: a :class:`ChangeProposal` is a proposal, never an applied
  change. Every :class:`~app.proposal.ProposedChange` defaults ``accepted=False``
  and there is no server-side code path that flips it True.
* Classification of an uploaded file must be **confirmed by a human** before the
  file is parsed — a critical-infrastructure file is never processed on a guess.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
