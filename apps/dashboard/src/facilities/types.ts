// Multi-facility administration types (client mirrors of the API payloads).
//
// These describe the *tenant-scoped* data the dashboard consumes: a tenant owns
// a set of facilities, each with its own configuration and role assignments, and
// the fleet roll-up aggregates health / energy / alerts across those facilities.

import type { DataProvenance, HealthBand } from '../api/types';

export type FacilityStatus = 'online' | 'maintenance' | 'offline';

export interface FacilityConfig {
  train_count: number;
  capacity_m3_day: number;
  currency: string;
  commissioned: string; // ISO date
  timezone: string;
}

export interface FacilityRoleAssignment {
  role: string; // e.g. 'facility-operator', 'engineer', 'viewer'
  subject: string; // stable identifier / username
  display_name: string;
}

export interface Facility {
  facility_id: string;
  tenant_id: string;
  tenant_name: string;
  name: string;
  region: string;
  status: FacilityStatus;
  config: FacilityConfig;
  roles: FacilityRoleAssignment[];
}

export interface FacilitiesResponse {
  tenant_id: string;
  facilities: Facility[];
  provenance: DataProvenance;
}

// --- Fleet roll-up ---------------------------------------------------------

export interface FacilityRollupHealth {
  score: number;
  band: HealthBand;
}

export interface FacilityRollupEnergy {
  total_power_kw: number;
  specific_energy_kwh_m3: number;
}

export interface FacilityRollup {
  facility_id: string;
  tenant_id: string;
  name: string;
  status: FacilityStatus;
  health: FacilityRollupHealth;
  energy: FacilityRollupEnergy;
  active_alarms: number;
  production_m3_day: number;
  provenance: DataProvenance;
}

export interface FleetTotals {
  facility_count: number;
  online_count: number;
  avg_health: number;
  worst_band: HealthBand;
  total_power_kw: number;
  total_production_m3_day: number;
  total_active_alarms: number;
}

export interface FleetOverview {
  tenant_id: string;
  facilities: FacilityRollup[];
  totals: FleetTotals;
  provenance: DataProvenance;
}
