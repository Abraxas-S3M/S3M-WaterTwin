# Data Provenance Reference

`DataProvenance` (defined in `packages/canonical_water_model/__init__.py`, mirrored
in `apps/dashboard/src/api/types.ts`) records **where a value came from**. It exists
so an operator can never mistake generated, claimed, or design-intent data for
verified live instrument readings.

Provenance is a *label about origin only*. It is **not** a confidence score, a
validation status, and it never authorizes a control action. S3M-WaterTwin is
read-only to OT: no provenance value enables a write to SCADA, PLC, OPC UA, or MQTT.

## Values

| Value | What it means | What it does NOT mean |
| --- | --- | --- |
| `synthetic` | Generated seed/pilot data produced by the platform. | Not from the plant; not measured, simulated, or claimed by anyone. |
| `simulated` | Output of a model/simulation run. | Not validated against the plant; not a live reading. |
| `preliminary` | An internal analytic result (health, RUL, forecast, risk) awaiting calibration/validation. | Not calibrated, not validated, not guaranteed. |
| `estimated` | An illustrative value/ROI figure derived from synthetic pilot data. | Not a validated saving or a guaranteed outcome. |
| `vendor_specified` | From an OEM datasheet, pump curve, or membrane projection. Authoritative for **design intent** only. | Not the current condition of the installed asset; not a live measurement. |
| `customer_supplied` | From a customer document, drawing, or design basis. Trusted as a **claim**. | Not verified against the plant; not a measurement; not platform-validated. |
| `customer_measured` | From a customer historian, LIMS, or instrument export. Real data. | Not live telemetry through the edge gateway; still subject to sensor-confidence scoring — not automatically trusted. |
| `measured` | **RESERVED** for live telemetry ingested through the edge gateway. | Not for customer file imports (use the `customer_*` values); not a control channel. |

The three `vendor_specified` / `customer_supplied` / `customer_measured` values are
the *customer-sourced* set — `is_customer_sourced(p)` returns `True` for exactly
these three and `False` for everything else, including live `measured` telemetry.

## Trust ordering (display only)

`PROVENANCE_RANK` encodes a trust ordering, lowest to highest confidence in
reflecting **plant reality**:

```
synthetic < simulated < preliminary < estimated < customer_supplied
          < vendor_specified < customer_measured < measured
```

This ranking is for **UI sorting and badge styling only**. It must never be used
to auto-promote an analytic label. `customer_measured` deliberately ranks *below*
live `measured` telemetry because a customer export has not been verified against
this plant's live instruments and is still subject to sensor-confidence scoring.

## The no-auto-promotion rule

**Ingesting customer data never changes an analytic's label from `preliminary` to
`calibrated`.**

Importing a vendor datasheet, a customer design document, or a customer
historian/LIMS export changes only the *provenance of the imported value itself*.
It does not retroactively upgrade any model output: a `preliminary` health score,
RUL, forecast, or risk stays `preliminary` until it is calibrated and validated
through the platform's own validation path. Provenance describes origin; it is not
a shortcut to a higher validation status. Any promotion to a calibrated/validated
label is a separate, explicit, audited step — not a side effect of ingestion.
