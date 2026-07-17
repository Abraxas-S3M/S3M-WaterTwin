// Tenant/facility scoping — the client-side guard that guarantees a signed-in
// identity only ever sees data for facilities it is entitled to.
//
// SECURITY: the API is the authoritative enforcer of tenant isolation, but the
// SPA applies these pure functions as defence in depth so that cross-tenant
// rows never render even if an upstream response were to over-return. Every
// consumer (facility switcher, fleet roll-up, administration panel) filters
// through `scopeFacilities` / `scopeFleet` before rendering.

import { canManageFacilities } from '../auth/roles';
import type { HealthBand } from '../api/types';
import type { Facility, FacilityRollup, FleetOverview, FleetTotals } from './types';

export interface FacilityScope {
  tenantId: string | null;
  facilityIds: string[];
  roles: readonly string[];
}

// Anything scopeable carries its owning tenant and its own id.
interface TenantScoped {
  facility_id: string;
  tenant_id: string;
}

/**
 * Is a single facility-like item visible to the given identity?
 *
 * Rules (evaluated in order):
 *  1. No tenant on the session -> nothing is visible.
 *  2. Different tenant -> never visible (hard cross-tenant boundary).
 *  3. Tenant-admin / admin -> every facility within their tenant.
 *  4. Otherwise (facility-operator, operator, viewer, ...) -> only the
 *     facilities explicitly assigned to the identity (`facilityIds`).
 */
export function isFacilityVisible(item: TenantScoped, scope: FacilityScope): boolean {
  if (!scope.tenantId) return false;
  if (item.tenant_id !== scope.tenantId) return false;
  if (canManageFacilities(scope.roles)) return true;
  return scope.facilityIds.includes(item.facility_id);
}

/** Facilities visible to the identity, with all cross-tenant rows removed. */
export function scopeFacilities(
  facilities: readonly Facility[],
  scope: FacilityScope,
): Facility[] {
  return facilities.filter((f) => isFacilityVisible(f, scope));
}

/** The ids of the facilities visible to the identity. */
export function visibleFacilityIds(
  facilities: readonly Facility[],
  scope: FacilityScope,
): string[] {
  return scopeFacilities(facilities, scope).map((f) => f.facility_id);
}

// Health bands ordered worst -> best so the fleet roll-up can surface the
// worst-case facility.
const BAND_SEVERITY: Record<HealthBand, number> = {
  Critical: 4,
  HighRisk: 3,
  Degraded: 2,
  Monitor: 1,
  Healthy: 0,
};

function worstBand(bands: readonly HealthBand[]): HealthBand {
  let worst: HealthBand = 'Healthy';
  for (const b of bands) {
    if (BAND_SEVERITY[b] > BAND_SEVERITY[worst]) worst = b;
  }
  return worst;
}

/** Recompute fleet totals from a set of (already-scoped) per-facility rollups. */
export function computeFleetTotals(rollups: readonly FacilityRollup[]): FleetTotals {
  const facility_count = rollups.length;
  const total_power_kw = rollups.reduce((sum, r) => sum + r.energy.total_power_kw, 0);
  const total_production_m3_day = rollups.reduce((sum, r) => sum + r.production_m3_day, 0);
  const total_active_alarms = rollups.reduce((sum, r) => sum + r.active_alarms, 0);
  const online_count = rollups.filter((r) => r.status === 'online').length;
  const avg_health =
    facility_count === 0
      ? 0
      : rollups.reduce((sum, r) => sum + r.health.score, 0) / facility_count;
  return {
    facility_count,
    online_count,
    avg_health,
    worst_band: worstBand(rollups.map((r) => r.health.band)),
    total_power_kw,
    total_production_m3_day,
    total_active_alarms,
  };
}

/**
 * Scope a fleet roll-up to the identity: drop any facility outside the tenant /
 * entitlement and RECOMPUTE the totals so aggregates never include foreign data.
 */
export function scopeFleet(fleet: FleetOverview, scope: FacilityScope): FleetOverview {
  const facilities = fleet.facilities.filter((r) => isFacilityVisible(r, scope));
  return {
    tenant_id: scope.tenantId ?? fleet.tenant_id,
    facilities,
    totals: computeFleetTotals(facilities),
    provenance: fleet.provenance,
  };
}
