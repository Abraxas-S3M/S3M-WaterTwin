"""watertwin-ingest: immutable customer-file intake service.

Optional, independently deployable. Receives customer files, stores them
immutably (content-addressed, write-once), scans them structurally, and tracks
them through a status lifecycle. No parsing. No direct database access. No OT
network access.
"""
