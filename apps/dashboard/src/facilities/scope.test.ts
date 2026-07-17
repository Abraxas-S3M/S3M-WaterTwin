import { describe, it, expect } from 'vitest';
import {
  computeFleetTotals,
  isFacilityVisible,
  scopeFacilities,
  scopeFleet,
  visibleFacilityIds,
  type FacilityScope,
} from './scope';
import {
  acmeFacilities,
  facilityAlpha,
  facilityOmegaForeign,
  fleetOverview,
  TENANT_ACME,
  TENANT_GLOBEX,
} from '../test/fixtures';
import type { FleetOverview } from './types';

const tenantAdmin: FacilityScope = {
  tenantId: TENANT_ACME,
  facilityIds: [],
  roles: ['tenant-admin'],
};

const facilityOperator: FacilityScope = {
  tenantId: TENANT_ACME,
  facilityIds: ['FAC-ALPHA'],
  roles: ['facility-operator'],
};

describe('scopeFacilities', () => {
  it('gives a tenant-admin every facility within their tenant', () => {
    const scoped = scopeFacilities(acmeFacilities, tenantAdmin);
    expect(scoped.map((f) => f.facility_id)).toEqual([
      'FAC-ALPHA',
      'FAC-BETA',
      'FAC-GAMMA',
    ]);
  });

  it('restricts a facility-operator to only their assigned facility', () => {
    const scoped = scopeFacilities(acmeFacilities, facilityOperator);
    expect(scoped.map((f) => f.facility_id)).toEqual(['FAC-ALPHA']);
  });

  it('never leaks a facility from another tenant (defence in depth)', () => {
    // Even if a cross-tenant row sneaks into the payload, it must be dropped.
    const raw = [...acmeFacilities, facilityOmegaForeign];
    const scoped = scopeFacilities(raw, tenantAdmin);
    expect(scoped.some((f) => f.tenant_id === TENANT_GLOBEX)).toBe(false);
    expect(scoped.some((f) => f.facility_id === 'FAC-OMEGA')).toBe(false);
  });

  it('returns nothing when the identity has no tenant', () => {
    const anon: FacilityScope = { tenantId: null, facilityIds: [], roles: [] };
    expect(scopeFacilities(acmeFacilities, anon)).toEqual([]);
  });

  it('returns nothing for a non-manager with no facility assignments', () => {
    const unassigned: FacilityScope = {
      tenantId: TENANT_ACME,
      facilityIds: [],
      roles: ['viewer'],
    };
    expect(scopeFacilities(acmeFacilities, unassigned)).toEqual([]);
  });

  it('treats a platform admin like a tenant manager within their tenant', () => {
    const admin: FacilityScope = { tenantId: TENANT_ACME, facilityIds: [], roles: ['admin'] };
    expect(visibleFacilityIds(acmeFacilities, admin)).toEqual([
      'FAC-ALPHA',
      'FAC-BETA',
      'FAC-GAMMA',
    ]);
  });
});

describe('isFacilityVisible', () => {
  it('hard-blocks a facility from a different tenant even for an admin', () => {
    const admin: FacilityScope = { tenantId: TENANT_ACME, facilityIds: [], roles: ['admin'] };
    expect(isFacilityVisible(facilityOmegaForeign, admin)).toBe(false);
    expect(isFacilityVisible(facilityAlpha, admin)).toBe(true);
  });
});

describe('computeFleetTotals', () => {
  it('rolls up health / energy / alerts across facilities', () => {
    const totals = computeFleetTotals(fleetOverview.facilities);
    expect(totals.facility_count).toBe(3);
    expect(totals.online_count).toBe(2);
    expect(totals.total_power_kw).toBe(1520 + 980 + 1750);
    expect(totals.total_production_m3_day).toBe(11952 + 8000 + 14000);
    expect(totals.total_active_alarms).toBe(1 + 3 + 0);
    expect(totals.avg_health).toBeCloseTo((79.5 + 62 + 91) / 3, 5);
    // Worst band across Monitor / Degraded / Healthy is Degraded.
    expect(totals.worst_band).toBe('Degraded');
  });

  it('is safe (zeroed) for an empty fleet', () => {
    const totals = computeFleetTotals([]);
    expect(totals.facility_count).toBe(0);
    expect(totals.avg_health).toBe(0);
    expect(totals.worst_band).toBe('Healthy');
    expect(totals.total_power_kw).toBe(0);
  });
});

describe('scopeFleet', () => {
  it('recomputes totals from only the facility-operator scoped facility', () => {
    const scoped = scopeFleet(fleetOverview, facilityOperator);
    expect(scoped.facilities.map((f) => f.facility_id)).toEqual(['FAC-ALPHA']);
    expect(scoped.totals.facility_count).toBe(1);
    expect(scoped.totals.total_power_kw).toBe(1520);
    expect(scoped.totals.total_active_alarms).toBe(1);
    expect(scoped.totals.avg_health).toBeCloseTo(79.5, 5);
  });

  it('drops a foreign-tenant facility and excludes it from the totals', () => {
    const leaky: FleetOverview = {
      ...fleetOverview,
      facilities: [
        ...fleetOverview.facilities,
        {
          facility_id: 'FAC-OMEGA',
          tenant_id: TENANT_GLOBEX,
          name: 'SWRO Omega',
          status: 'online',
          health: { score: 10, band: 'Critical' },
          energy: { total_power_kw: 9999, specific_energy_kwh_m3: 5 },
          active_alarms: 42,
          production_m3_day: 20000,
          provenance: 'preliminary',
        },
      ],
    };
    const scoped = scopeFleet(leaky, tenantAdmin);
    expect(scoped.facilities.some((f) => f.tenant_id === TENANT_GLOBEX)).toBe(false);
    // Foreign power/alarms must not contaminate the aggregate.
    expect(scoped.totals.total_power_kw).toBe(1520 + 980 + 1750);
    expect(scoped.totals.total_active_alarms).toBe(4);
    expect(scoped.totals.worst_band).toBe('Degraded');
  });
});
