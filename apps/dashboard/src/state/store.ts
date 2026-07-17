// Light global UI state (zustand): selected asset and scenario selection.
// NOTE: This holds ephemeral UI selection only. Per Phase 7 constraints, we do
// NOT persist application data in localStorage — nothing here is written to
// browser storage; it lives in memory for the session.

import { create } from 'zustand';
import { DEFAULT_UNIT_SYSTEM, type UnitSystem } from '../i18n/units';

export type ScenarioId = 'baseline' | 'peak_demand' | 'fouling_event' | 'energy_saver';

// Scenario UI labels/descriptions are localized via the `scenarios.items.<id>`
// keys; the store only tracks the selectable ids in flow order.
export const SCENARIO_IDS: ScenarioId[] = [
  'baseline',
  'peak_demand',
  'fouling_event',
  'energy_saver',
];

export type PageId =
  | 'command'
  | 'process'
  | 'asset'
  | 'simulation'
  | 'water-quality'
  | 'predictive-maintenance'
  | 'maintenance-center'
  | 'energy'
  | 'resilience'
  | 'executive'
  | 'assistant'
  | 'models';
  | 'security';
  | 'admin-facilities';
  | 'training';

interface DashboardState {
  page: PageId;
  selectedAssetId: string | null;
  selectedStage: string | null;
  scenario: ScenarioId;
  operatorName: string;
  // The facility currently in focus in the shell switcher. Ephemeral UI state;
  // it is validated against the identity's scoped facilities before use so it can
  // never point at a facility outside the caller's tenant/entitlement.
  activeFacilityId: string | null;
  /** Preferred measurement system. Metric is the product default. */
  unitSystem: UnitSystem;
  navigate: (page: PageId) => void;
  setSelectedAsset: (assetId: string | null) => void;
  openAssetTwin: (assetId: string) => void;
  setSelectedStage: (stage: string | null) => void;
  setScenario: (scenario: ScenarioId) => void;
  setOperatorName: (name: string) => void;
  setActiveFacility: (facilityId: string | null) => void;
  setUnitSystem: (unitSystem: UnitSystem) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  page: 'command',
  selectedAssetId: null,
  selectedStage: null,
  scenario: 'baseline',
  operatorName: 'operator',
  activeFacilityId: null,
  unitSystem: DEFAULT_UNIT_SYSTEM,
  navigate: (page) => set({ page }),
  setSelectedAsset: (assetId) => set({ selectedAssetId: assetId }),
  openAssetTwin: (assetId) => set({ selectedAssetId: assetId, page: 'asset' }),
  setSelectedStage: (stage) => set({ selectedStage: stage }),
  setScenario: (scenario) => set({ scenario }),
  setOperatorName: (name) => set({ operatorName: name }),
  setActiveFacility: (facilityId) => set({ activeFacilityId: facilityId }),
  setUnitSystem: (unitSystem) => set({ unitSystem }),
}));
