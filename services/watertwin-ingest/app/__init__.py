"""watertwin-ingest: advisory file-intake service for the S3M-WaterTwin platform.

Turns an uploaded file (EPANET .inp in this phase) into a draft configuration
change through watertwin-api's EXISTING configuration lifecycle. The service is
read-only to OT: it never writes to SCADA/PLC/OPC UA/MQTT and never issues a
control command. Every proposed change is human-reviewed and approved through
the existing approval workflow; separation of duties is enforced server-side.
"""
