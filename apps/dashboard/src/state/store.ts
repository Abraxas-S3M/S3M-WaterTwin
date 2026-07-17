// Light global UI state (zustand): selected asset and scenario selection.
// NOTE: This holds ephemeral UI selection only. Per Phase 7 constraints, we do
// NOT persist application data in localStorage — nothing here is written to
// browser storage; it lives in memory for the session.

import { create } from 'zustand';

export type ScenarioId = 'baseline' | 'peak_demand' | 'fouling_event' | 'energy_saver';

export interface Scenario {
  id: ScenarioId;
  label: string;
  description: string;
}

export const SCENARIOS: Scenario[] = [
  {
    id: 'baseline',
    label: 'Baseline',
    description: 'Nominal operating conditions from the live twin.',
  },
  {
    id: 'peak_demand',
    label: 'Peak Demand',
    description: 'Higher product-water demand profile (simulation, later phase).',
  },
  {
    id: 'fouling_event',
    label: 'Membrane Fouling',
    description: 'Progressive fouling stressor (simulation, later phase).',
  },
  {
    id: 'energy_saver',
    label: 'Energy Saver',
    description: 'Minimize specific energy within limits (simulation, later phase).',
  },
];

export type PageId =
  | 'command'
  | 'process'
  | 'asset'
  | 'simulation'
  | 'water-quality'
  | 'predictive-maintenance'
  | 'energy'
  | 'resilience'
  | 'executive'
  | 'assistant'
  | 'admin-facilities';

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
  navigate: (page: PageId) => void;
  setSelectedAsset: (assetId: string | null) => void;
  openAssetTwin: (assetId: string) => void;
  setSelectedStage: (stage: string | null) => void;
  setScenario: (scenario: ScenarioId) => void;
  setOperatorName: (name: string) => void;
  setActiveFacility: (facilityId: string | null) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  page: 'command',
  selectedAssetId: null,
  selectedStage: null,
  scenario: 'baseline',
  operatorName: 'operator',
  activeFacilityId: null,
  navigate: (page) => set({ page }),
  setSelectedAsset: (assetId) => set({ selectedAssetId: assetId }),
  openAssetTwin: (assetId) => set({ selectedAssetId: assetId, page: 'asset' }),
  setSelectedStage: (stage) => set({ selectedStage: stage }),
  setScenario: (scenario) => set({ scenario }),
  setOperatorName: (name) => set({ operatorName: name }),
  setActiveFacility: (facilityId) => set({ activeFacilityId: facilityId }),
}));
