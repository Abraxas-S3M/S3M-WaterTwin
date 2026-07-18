# watertwin-ingest — network policy (deny-all egress)

The ingest service runs untrusted-file parsers, so its network posture is
**deny-all egress by default** with a tiny explicit allowlist. This is enforced
at two layers that are kept in sync and both asserted by the test suite:

1. **Network layer** — a Kubernetes `NetworkPolicy`
   (`services/watertwin-ingest/deploy/networkpolicy.yaml`).
2. **Application layer** — the egress guard (`services/watertwin-ingest/app/egress.py`),
   which refuses any connection not on the allowlist and *always* refuses OT
   destinations.

Test of record: `security/tests/test_t11_egress.py` (ADR-0014 row **T11**).

## Allowed egress (the entire allowlist)

| Destination | Port | Why |
|-------------|------|-----|
| kube-dns | 53/UDP, 53/TCP | DNS resolution only |
| `watertwin-api` | 8000/TCP | In-cluster advisory API (the platform) |
| S3M endpoint | 443/TCP | The S3M platform (restrict the CIDR to your S3M egress gateway) |

Nothing else is permitted. There is **no** egress rule for any OT CIDR, MQTT
(1883/8883), OPC UA (4840), Modbus (502), DNP3 (20000) or EtherNet/IP (44818).
Because a `NetworkPolicy` is allow-list based, omitting these rules denies them by
default — a bug in the service cannot open a path to the OT zone.

## Ingress

Only the dashboard and `watertwin-api` may reach the ingest API on port 8300.

## Why two layers?

The `NetworkPolicy` is the authoritative network control. The application-layer
guard is defence-in-depth: it fails closed even in environments where a
`NetworkPolicy` is misconfigured or absent (e.g. local Docker), and it turns an
attempt to reach OT into a loud, testable `OTNetworkForbidden` error rather than
a silent packet drop. The two are asserted to agree:

- `test_ot_ports_always_denied` / `test_cannot_allowlist_an_ot_destination`
  prove the application guard.
- `test_networkpolicy_manifest_has_no_ot_egress` parses the shipped manifest and
  fails if any OT/MQTT/OPC UA port ever appears in an egress rule.

## Assertion: the ingest service cannot reach OT, MQTT or OPC UA

The forbidden set (`app/egress.OT_FORBIDDEN_PORTS`) is: MQTT `1883`, MQTTS
`8883`, OPC UA `4840`, Modbus `502`, DNP3 `20000`, EtherNet/IP `44818`, IEC 61850
/ S7 `102`, IEC 60870-5-104 `2404`. OT host suffixes (`.ot.local`, `.scada.local`,
`.plc.local`) are also always denied. These cannot be added to the allowlist —
`EgressPolicy.allow()` raises `OTNetworkForbidden` if you try.
