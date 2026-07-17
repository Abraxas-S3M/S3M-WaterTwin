"""Multi-facility administration + fleet roll-up (advisory, read-only).

This module exposes a *tenant-scoped* view of the facilities an authenticated
identity may see. It is the authoritative enforcer of tenant isolation: every
response is filtered to the caller's ``Principal`` so cross-tenant rows are never
returned. Facilities are advisory metadata + synthetic roll-up metrics only;
nothing here writes to any control system.

Scoping rules (mirrored client-side as defence in depth):
  * No tenant on the principal -> nothing is visible.
  * Different tenant -> never visible (hard cross-tenant boundary).
  * tenant-admin / admin -> every facility within their tenant.
  * Otherwise (facility-operator, ...) -> only the facilities explicitly
    assigned to the identity (``facility_ids``).
"""

from __future__ import annotations

from typing import Any

from canonical_water_model import DataProvenance

from .auth import Principal

# Health bands ordered worst -> best so the fleet roll-up can surface the
# worst-case facility across the fleet.
_BAND_SEVERITY: dict[str, int] = {
    "Critical": 4,
    "HighRisk": 3,
    "Degraded": 2,
    "Monitor": 1,
    "Healthy": 0,
}


# Static demo catalog spanning two tenants. In a real deployment this is backed
# by the tenant/facility registry; here it is an in-repo catalog sufficient for
# the advisory console. Tenant isolation is enforced by scoping every response
# to the caller's principal (never by trusting the client).
_CATALOG: list[dict[str, Any]] = [
    {
        "facility_id": "FAC-ALPHA",
        "tenant_id": "TEN-ACME",
        "tenant_name": "Acme Water Co",
        "name": "SWRO Alpha",
        "region": "Gulf Coast",
        "status": "online",
        "config": {
            "train_count": 3,
            "capacity_m3_day": 12000,
            "currency": "USD",
            "commissioned": "2021-03-15",
            "timezone": "America/Chicago",
        },
        "roles": [
            {"role": "facility-operator", "subject": "ola-operator", "display_name": "Ola Operator"},
            {"role": "engineer", "subject": "erin-engineer", "display_name": "Erin Engineer"},
            {"role": "viewer", "subject": "val-viewer", "display_name": "Val Viewer"},
        ],
    },
    {
        "facility_id": "FAC-BETA",
        "tenant_id": "TEN-ACME",
        "tenant_name": "Acme Water Co",
        "name": "SWRO Beta",
        "region": "Adriatic",
        "status": "maintenance",
        "config": {
            "train_count": 2,
            "capacity_m3_day": 8000,
            "currency": "EUR",
            "commissioned": "2022-09-01",
            "timezone": "Europe/Rome",
        },
        "roles": [
            {"role": "facility-operator", "subject": "bo-operator", "display_name": "Bo Operator"},
        ],
    },
    {
        "facility_id": "FAC-GAMMA",
        "tenant_id": "TEN-ACME",
        "tenant_name": "Acme Water Co",
        "name": "SWRO Gamma",
        "region": "Red Sea",
        "status": "online",
        "config": {
            "train_count": 4,
            "capacity_m3_day": 14000,
            "currency": "USD",
            "commissioned": "2020-01-20",
            "timezone": "Asia/Riyadh",
        },
        "roles": [
            {"role": "engineer", "subject": "gia-engineer", "display_name": "Gia Engineer"},
        ],
    },
    {
        "facility_id": "FAC-OMEGA",
        "tenant_id": "TEN-GLOBEX",
        "tenant_name": "Globex Desal",
        "name": "SWRO Omega",
        "region": "Pacific",
        "status": "online",
        "config": {
            "train_count": 5,
            "capacity_m3_day": 20000,
            "currency": "USD",
            "commissioned": "2019-06-10",
            "timezone": "Australia/Perth",
        },
        "roles": [
            {"role": "facility-operator", "subject": "omar-operator", "display_name": "Omar Operator"},
        ],
    },
]

# Synthetic per-facility roll-up metrics (advisory, preliminary).
_ROLLUP: dict[str, dict[str, Any]] = {
    "FAC-ALPHA": {
        "health": {"score": 79.5, "band": "Monitor"},
        "energy": {"total_power_kw": 1520.0, "specific_energy_kwh_m3": 3.05},
        "active_alarms": 1,
        "production_m3_day": 11952.0,
    },
    "FAC-BETA": {
        "health": {"score": 62.0, "band": "Degraded"},
        "energy": {"total_power_kw": 980.0, "specific_energy_kwh_m3": 3.4},
        "active_alarms": 3,
        "production_m3_day": 8000.0,
    },
    "FAC-GAMMA": {
        "health": {"score": 91.0, "band": "Healthy"},
        "energy": {"total_power_kw": 1750.0, "specific_energy_kwh_m3": 2.8},
        "active_alarms": 0,
        "production_m3_day": 14000.0,
    },
    "FAC-OMEGA": {
        "health": {"score": 55.0, "band": "Degraded"},
        "energy": {"total_power_kw": 2100.0, "specific_energy_kwh_m3": 3.1},
        "active_alarms": 5,
        "production_m3_day": 20000.0,
    },
}


def _is_visible(principal: Principal, tenant_id: str, facility_id: str) -> bool:
    """Whether ``principal`` may see the given facility (tenant-isolated)."""
    if not principal.tenant_id:
        return False
    if tenant_id != principal.tenant_id:
        return False
    if principal.can_manage_facilities():
        return True
    return facility_id in principal.facility_ids


def _scoped_catalog(principal: Principal) -> list[dict[str, Any]]:
    return [
        f
        for f in _CATALOG
        if _is_visible(principal, f["tenant_id"], f["facility_id"])
    ]


def list_facilities(principal: Principal) -> dict[str, Any]:
    """Facilities visible to ``principal`` (scoped to their tenant/entitlement)."""
    facilities = [dict(f) for f in _scoped_catalog(principal)]
    return {
        "tenant_id": principal.tenant_id,
        "facilities": facilities,
        "provenance": DataProvenance.preliminary.value,
    }


def _worst_band(bands: list[str]) -> str:
    worst = "Healthy"
    for band in bands:
        if _BAND_SEVERITY.get(band, 0) > _BAND_SEVERITY.get(worst, 0):
            worst = band
    return worst


def _rollup_row(facility: dict[str, Any]) -> dict[str, Any]:
    metrics = _ROLLUP[facility["facility_id"]]
    return {
        "facility_id": facility["facility_id"],
        "tenant_id": facility["tenant_id"],
        "name": facility["name"],
        "status": facility["status"],
        "health": dict(metrics["health"]),
        "energy": dict(metrics["energy"]),
        "active_alarms": metrics["active_alarms"],
        "production_m3_day": metrics["production_m3_day"],
        "provenance": DataProvenance.preliminary.value,
    }


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    avg_health = (
        sum(r["health"]["score"] for r in rows) / count if count else 0.0
    )
    return {
        "facility_count": count,
        "online_count": sum(1 for r in rows if r["status"] == "online"),
        "avg_health": round(avg_health, 4),
        "worst_band": _worst_band([r["health"]["band"] for r in rows]),
        "total_power_kw": round(sum(r["energy"]["total_power_kw"] for r in rows), 4),
        "total_production_m3_day": round(
            sum(r["production_m3_day"] for r in rows), 4
        ),
        "total_active_alarms": sum(r["active_alarms"] for r in rows),
    }


def fleet_overview(principal: Principal) -> dict[str, Any]:
    """Fleet roll-up (health/energy/alerts) across the principal's facilities.

    Totals are computed from the scoped rows only, so foreign-tenant metrics can
    never contaminate the aggregate.
    """
    rows = [_rollup_row(f) for f in _scoped_catalog(principal)]
    return {
        "tenant_id": principal.tenant_id,
        "facilities": rows,
        "totals": _totals(rows),
        "provenance": DataProvenance.preliminary.value,
    }
