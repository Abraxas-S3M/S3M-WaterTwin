"""watertwin-ingest: templated spreadsheet ingestion for the workbench.

Read-only, decision-support ingestion of the three highest-volume hand-entry
burdens -- equipment specifications, OT tag mappings and lab methods -- from
customer-filled CSV/XLSX templates into a reviewable diff. This service parses
uploaded files only; it never connects to, or writes to, any OT/SCADA/PLC/OPC
UA/MQTT system, and it issues no control commands.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
