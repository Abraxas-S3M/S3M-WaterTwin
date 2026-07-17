import type {
  Asset,
  AnomalyResult,
  AuditResponse,
  ControlBoundary,
  HealthScore,
  PlantOverview,
  PumpCurve,
  RecommendationCard,
  TelemetryReading,
} from '../api/types';

export const controlBoundary: ControlBoundary = {
  control_mode: 'advisory',
  operator_approval_required: true,
  control_write_enabled: false,
};

export const hpAsset: Asset = {
  asset_id: 'AST-HPP-01',
  name: 'High-Pressure Pump A',
  asset_type: 'hp_pump',
  facility_id: 'SWRO-ALPHA',
  train_id: 'TRAIN-01',
  treatment_stage: 'high_pressure_pumping',
  parent_id: null,
  manufacturer: 'KSB',
  model: 'Multitec-HP',
  serial_number: 'SN-AST-HPP-01',
  location: 'SWRO-ALPHA/TRAIN-01/high_pressure_pumping',
  criticality: 'critical',
  rated: {
    rated_flow_m3h: 520,
    rated_head_m: 680,
    rated_power_kw: 1250,
    bep_flow_m3h: 500,
    max_flow_m3h: 560,
  },
  install_date: '2021-03-15',
};

export const assets: Asset[] = [hpAsset];

export const hpHealth: HealthScore = {
  asset_id: 'AST-HPP-01',
  score: 63.2,
  band: 'Degraded',
  provenance: 'preliminary',
  contributions: [
    { factor: 'Vibration trend', delta: -8.1, detail: 'RMS velocity vs rated limit' },
    { factor: 'Efficiency drift', delta: -6.0, detail: 'vs commissioning baseline' },
  ],
};

export const hpAnomaly: AnomalyResult = {
  asset_id: 'AST-HPP-01',
  score: 0.61,
  ranked_domains: [
    ['mechanical', 0.55],
    ['hydraulic', 0.36],
  ],
  factors: { vibration_rms: 0.5 },
  provenance: 'preliminary',
};

export const hpTelemetry: TelemetryReading[] = [
  {
    asset_id: 'AST-HPP-01',
    metric: 'flow_m3h',
    value: 505,
    unit: 'm³/h',
    timestamp: '2026-07-17T07:00:00Z',
    provenance: 'synthetic',
    quality: 'good',
  },
  {
    asset_id: 'AST-HPP-01',
    metric: 'discharge_pressure_bar',
    value: 66,
    unit: 'bar',
    timestamp: '2026-07-17T07:00:00Z',
    provenance: 'synthetic',
    quality: 'good',
  },
];

export const hpPumpCurve: PumpCurve = {
  asset_id: 'AST-HPP-01',
  supported: true,
  provenance: 'synthetic',
  bep: { flow_m3h: 500, head_m: 680 },
  operating_point: { flow_m3h: 505, head_m: 675 },
  curve: [
    { flow_m3h: 0, head_m: 850, efficiency_pct: 0 },
    { flow_m3h: 500, head_m: 680, efficiency_pct: 100 },
    { flow_m3h: 560, head_m: 600, efficiency_pct: 85 },
  ],
};

export const recommendation: RecommendationCard = {
  recommendation_id: 'REC-TEST0001',
  packet_id: 'PKT-TEST0001',
  facility_id: 'SWRO-ALPHA',
  train_id: 'TRAIN-01',
  asset_id: 'AST-HPP-01',
  treatment_stage: 'high_pressure_pumping',
  summary: 'High-Pressure Pump A: health 63.2 (Degraded), anomaly 0.61.',
  ranked_causes: [
    {
      cause: 'Impeller wear reducing hydraulic efficiency',
      probability: 0.46,
      evidence: 'Operating point drifted below curve',
    },
  ],
  recommended_action: 'Schedule vibration diagnostic and inspect drive-end bearing.',
  confidence: 0.74,
  evidence: {
    telemetry_window: '14d',
    assets_reviewed: ['AST-HPP-01'],
    documents_reviewed: [],
    simulation_ids: [],
    assumptions: ['Synthetic telemetry used in place of live plant historian'],
    data_timestamp: '2026-07-17T07:00:00Z',
  },
  control_boundary: controlBoundary,
  approval_status: 'pending',
  source_engine_status: 'preliminary',
  created_at: '2026-07-17T07:00:00Z',
};

export const audit: AuditResponse = {
  provenance: 'preliminary',
  entries: [
    {
      id: 'aud-1',
      timestamp: '2026-07-17T07:00:00Z',
      action: 'recommendation_created',
      recommendation_id: 'REC-TEST0001',
      asset_id: 'AST-HPP-01',
      actor: 's3m-engine',
      detail: 'Recommendation created',
    },
  ],
};

export const overview: PlantOverview = {
  facility_id: 'SWRO-ALPHA',
  train_id: 'TRAIN-01',
  provenance: 'preliminary',
  plant_health: { score: 79.5, band: 'Monitor', provenance: 'preliminary' },
  production: {
    permeate_flow_m3h: 498,
    product_m3_per_day: 11952,
    feed_flow_m3h: 505,
    provenance: 'synthetic',
  },
  recovery_pct: { value: 44, provenance: 'synthetic' },
  permeate_conductivity_us_cm: { value: 285, provenance: 'synthetic' },
  energy: { total_power_kw: 1520, specific_energy_kwh_m3: 3.05, provenance: 'synthetic' },
  hp_pump_status: {
    asset_id: 'AST-HPP-01',
    health: 63.2,
    band: 'Degraded',
    anomaly: 0.61,
    provenance: 'preliminary',
  },
  membrane_status: {
    asset_id: 'AST-MEMB-01',
    health: 71,
    band: 'Degraded',
    normalized_salt_passage_pct: 1.8,
    provenance: 'preliminary',
  },
  active_alarms: [
    {
      asset_id: 'AST-HPP-01',
      asset_name: 'High-Pressure Pump A',
      severity: 'high',
      message: 'High-Pressure Pump A: health 63.2 (Degraded), anomaly 0.61',
      provenance: 'preliminary',
    },
  ],
  active_recommendations: [recommendation],
  service_continuity_risk: { score: 34, band: 'elevated', provenance: 'preliminary' },
};
