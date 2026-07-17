import type {
  Asset,
  AnomalyResult,
  AuditResponse,
  ControlBoundary,
  EquipmentEnvelopeResponse,
  EquipmentFailureProbabilityResponse,
  EquipmentHealthResponse,
  EquipmentRootCauseResponse,
  EquipmentRulResponse,
  HealthScore,
  MaintenanceRankingResponse,
  MaintenanceRecommendationsResponse,
  MembraneHealthResponse,
  PlantOverview,
  PumpCurve,
  RecommendationCard,
  TelemetryReading,
  WQAlertsResponse,
  WQContaminantMatrixResponse,
  WQForecastResponse,
  WQRemovalResponse,
  WQScalingResponse,
  WQStatusResponse,
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

const wqEnvelope = {
  facility_id: 'S3M-DESAL-01',
  train_id: 'RO-TRAIN-001',
  control_boundary: controlBoundary,
};

export const wqStatus: WQStatusResponse = {
  ...wqEnvelope,
  provenance: 'synthetic',
  stage_status: [
    {
      stage: 'intake',
      location: 'intake',
      provenance: 'synthetic',
      compliance: [{ variable: 'turbidity_ntu', value: 2.2, limit: 0.3, within_limit: false }],
    },
    {
      stage: 'permeate',
      location: 'permeate',
      provenance: 'synthetic',
      compliance: [{ variable: 'tds_mg_l', value: 401, limit: 500, within_limit: true }],
      recovery: 0.317,
      salt_rejection: 0.99109,
      salt_passage: 0.00891,
    },
  ],
  samples: [
    {
      sample_id: 'WQS-SP-01-t0',
      sampling_point_id: 'SP-01',
      stage: 'intake',
      stream_id: 'STR-SW-FEED',
      timestamp: '2026-07-17T07:00:00Z',
      provenance: 'synthetic',
      measurements: { turbidity_ntu: 2.2, sdi: 5.6, boron_mg_l: 5.0 },
      sample_type: 'continuous',
      method: 'online analyzer',
      detection_limit: 0.01,
      limit: null,
      qc_status: 'pass',
    },
  ],
  summary: {
    recovery: 0.317,
    salt_rejection: 0.99109,
    salt_passage: 0.00891,
    normalized_salt_passage: 0.00865,
    normalized_dp_bar: 1.0,
    permeate_tds_mg_l: 401.0,
    permeate_boron_mg_l: 0.582,
  },
};

export const wqContaminantMatrix: WQContaminantMatrixResponse = {
  ...wqEnvelope,
  provenance: 'synthetic',
  rows: [
    {
      contaminant: 'Boron',
      unit: 'mg/L',
      intake: 5.0,
      post_pretreatment: 5.0,
      ro_feed: 5.0,
      permeate: 0.582,
      finished: 0.582,
      brine: 7.3,
      removal_pct: 88.4,
      limit: 1.0,
      provenance: 'synthetic',
    },
    {
      contaminant: 'TDS',
      unit: 'mg/L',
      intake: 45000,
      post_pretreatment: 45000,
      ro_feed: 45000,
      permeate: 401,
      finished: 521,
      brine: 65700,
      removal_pct: 98.8,
      limit: 500,
      provenance: 'synthetic',
    },
  ],
};

export const wqRemoval: WQRemovalResponse = {
  ...wqEnvelope,
  provenance: 'preliminary',
  removal: [
    {
      contaminant: 'Boron',
      unit: '%',
      current_pct: 88.4,
      design_pct: 90.0,
      predicted_pct: 87.8,
      confidence: 0.67,
      provenance: 'preliminary',
    },
    {
      contaminant: 'TDS',
      unit: '%',
      current_pct: 98.8,
      design_pct: 99.4,
      predicted_pct: 98.2,
      confidence: 0.67,
      provenance: 'preliminary',
    },
  ],
};

export const wqScaling: WQScalingResponse = {
  ...wqEnvelope,
  provenance: 'preliminary',
  scaling: [
    {
      compound: 'CaCO3',
      saturation: 0.775,
      probability: 0.31,
      ro_stage_at_risk: 'ro_stage_2',
      max_safe_recovery: 0.45,
      recommended_antiscalant_note: 'Acid/antiscalant dosing indicated (preliminary).',
      provenance: 'preliminary',
    },
    {
      compound: 'BaSO4',
      saturation: 2.68,
      probability: 1.0,
      ro_stage_at_risk: 'ro_stage_2',
      max_safe_recovery: 0.45,
      recommended_antiscalant_note: 'BaSO4 super-saturated (preliminary).',
      provenance: 'preliminary',
    },
  ],
};

export const wqForecast: WQForecastResponse = {
  ...wqEnvelope,
  provenance: 'preliminary',
  forecasts: [
    {
      target: 'permeate_salinity',
      unit: 'mg/L TDS',
      horizon: '24h',
      predicted_value: 404.2,
      lower: 380.0,
      upper: 428.4,
      confidence: 0.71,
      basis: 'normalized salt-passage trend (preliminary)',
      provenance: 'preliminary',
    },
    {
      target: 'permeate_boron',
      unit: 'mg/L',
      horizon: '24h',
      predicted_value: 0.6,
      lower: 0.55,
      upper: 0.65,
      confidence: 0.71,
      basis: 'pKa speciation (preliminary)',
      provenance: 'preliminary',
    },
    {
      target: 'scaling_time_to_critical:BaSO4',
      unit: 'h',
      horizon: '7d',
      predicted_value: 4.0,
      lower: 2.4,
      upper: 6.4,
      confidence: 0.45,
      basis: 'dominant scale BaSO4 (preliminary)',
      provenance: 'preliminary',
    },
    {
      target: 'fouling_risk',
      unit: 'index 0-1',
      horizon: '24h',
      predicted_value: 0.42,
      lower: 0.33,
      upper: 0.51,
      confidence: 0.71,
      basis: 'normalized dP + ATP + UV254 (preliminary)',
      provenance: 'preliminary',
    },
  ],
};

export const wqAlerts: WQAlertsResponse = {
  ...wqEnvelope,
  provenance: 'preliminary',
  alerts: [
    {
      code: 'WQ-SCALING-BASO4',
      stage: 'ro_stage_2',
      cause: 'BaSO4 scaling risk elevated in concentrate (saturation 2.68, p=1.00).',
      horizon: 'shift',
      confidence: 0.8,
      recommended_action: 'Verify antiscalant dosing / reduce recovery; advisory only.',
      approval_required: true,
      provenance: 'preliminary',
    },
  ],
  recommendations: [
    {
      ...recommendation,
      recommendation_id: 'rec-wq-wq-scaling-baso4',
      summary: 'BaSO4 scaling risk elevated in concentrate (saturation 2.68, p=1.00).',
      recommended_action: 'Verify antiscalant dosing / reduce recovery; advisory only.',
      source_engine_status: 'water-quality: preliminary',
      approval_status: 'pending',
    },
  ],
};

// --- Equipment & Membrane Intelligence + Predictive Maintenance ---

const pdmEnvelope = {
  facility_id: 'S3M-DESAL-01',
  train_id: 'RO-TRAIN-001',
  provenance: 'preliminary' as const,
  control_boundary: controlBoundary,
};

export const equipmentHealth: EquipmentHealthResponse = {
  ...pdmEnvelope,
  health: {
    asset_id: 'AST-HPP-01',
    component_type: 'pump',
    score: 62.5,
    band: 'Degraded',
    provenance: 'preliminary',
    contributions: [
      { factor: 'Vibration', delta: -12.3, detail: '6.4 mm/s RMS vs 4.5 mm/s (ISO 10816)' },
      { factor: 'Bearing temperature', delta: -4.9, detail: '92 C bearing vs 90 C alarm limit' },
      { factor: 'Efficiency drift', delta: -12.0, detail: '6.0% below commissioning baseline' },
    ],
  },
};

export const equipmentRul: EquipmentRulResponse = {
  ...pdmEnvelope,
  rul: {
    asset_id: 'AST-HPP-01',
    rul_days: 96.0,
    lower_days: 48.0,
    upper_days: 144.0,
    method: 'health-slope extrapolation modulated by duty/maintenance/fleet',
    basis: [
      'health slope -2.75/day projects 96 d to threshold 30',
      'duty-cycle severity 0.82 -> x0.51',
    ],
    provenance: 'preliminary',
  },
};

export const equipmentFailureProbability: EquipmentFailureProbabilityResponse = {
  ...pdmEnvelope,
  failure_probability: {
    asset_id: 'AST-HPP-01',
    horizons: { '24h': 0.02, '7d': 0.14, '30d': 0.48, '90d': 0.83 },
    predicted_failure_mode: 'Progressive hydraulic-efficiency loss / bearing wear',
    provenance: 'preliminary',
  },
};

export const equipmentEnvelope: EquipmentEnvelopeResponse = {
  ...pdmEnvelope,
  envelope: {
    asset_id: 'AST-HPP-01',
    samples: 5,
    at_bep_fraction: 0.6,
    low_flow_fraction: 0.2,
    high_pressure_fraction: 0.2,
    excess_temperature_fraction: 0.2,
    cavitation_risk_fraction: 0.0,
    provenance: 'preliminary',
  },
};

export const equipmentRootCause: EquipmentRootCauseResponse = {
  ...pdmEnvelope,
  root_cause: {
    asset_id: 'AST-HPP-01',
    provenance: 'preliminary',
    ranked_causes: [
      {
        cause: 'Membrane fouling',
        probability: 0.44,
        evidence: 'WQ signal: normalized dP +12% and salt passage +8% vs baseline.',
      },
      {
        cause: 'Pump efficiency loss',
        probability: 0.23,
        evidence: 'Curve deviation: operating point 3% below pump efficiency curve.',
      },
      {
        cause: 'Feed salinity rise',
        probability: 0.18,
        evidence: 'Sensor value: feed salinity +2% raises osmotic demand.',
      },
      {
        cause: 'Valve restriction',
        probability: 0.1,
        evidence: 'Sensor value: valve position error 1%; throttling adds dP.',
      },
      {
        cause: 'Sensor error',
        probability: 0.05,
        evidence: 'Historical comparison: cross-sensor consistency 95%.',
      },
    ],
  },
};

export const membraneHealth: MembraneHealthResponse = {
  ...pdmEnvelope,
  membrane: {
    asset_id: 'AST-MEMB-01',
    score: 68.4,
    band: 'Degraded',
    provenance: 'preliminary',
    normalized_permeate_flow_decline_pct: 9.2,
    normalized_salt_passage_rise_pct: 12.5,
    normalized_dp_rise_pct: 18.1,
    fouling: { organic: 0.52, colloidal: 0.61, biological: 0.34, scaling: 0.71 },
    salt_passage_trend_pct_per_day: 0.42,
    cleaning_required: true,
    cleaning_reason: 'CIP indicated (advisory): normalized dP +18% >= 15% threshold',
    underperforming_vessel: 'RO-1-V18 (element 6, stage-2 tail)',
    contributions: [
      { factor: 'Salt passage rise', delta: -15.0, detail: 'normalized salt passage +12.5%' },
      { factor: 'Differential pressure rise', delta: -14.5, detail: 'normalized dP +18.1%' },
    ],
    rul: {
      asset_id: 'AST-MEMB-01',
      rul_days: 210.0,
      lower_days: 120.0,
      upper_days: 300.0,
      method: 'membrane health-slope extrapolation',
      basis: ['fouling-driven decline projected to CIP/replace threshold 40'],
      provenance: 'preliminary',
    },
  },
};

export const pdmRecommendationHpp = {
  asset_id: 'AST-HPP-01',
  asset_name: 'High-Pressure Pump A',
  predicted_failure_mode: 'Progressive hydraulic-efficiency loss / bearing wear',
  failure_probability_30d: 0.48,
  rul_days: 96.0,
  rul_lower_days: 48.0,
  rul_upper_days: 144.0,
  time_to_intervention_days: 34.0,
  recommended_window: 'Next low-demand window in ~34 d (overnight 02:00-06:00, off-peak demand)',
  spares_required: ['Drive-end bearing set', 'Mechanical seal cartridge'],
  expected_downtime_hours: 10.0,
  maintenance_cost: 28000.0,
  avoided_failure_cost: 185000.0,
  rank_score: 41.2,
  recommendation_id: 'rec-pdm-ast-hpp-01',
  control_boundary: controlBoundary,
  approval_status: 'pending' as const,
  provenance: 'preliminary' as const,
};

export const pdmRecommendationMemb = {
  asset_id: 'AST-MEMB-01',
  asset_name: 'RO Membrane Array (Train 1)',
  predicted_failure_mode: 'Irreversible fouling / salt-passage breakthrough',
  failure_probability_30d: 0.31,
  rul_days: 210.0,
  rul_lower_days: 120.0,
  rul_upper_days: 300.0,
  time_to_intervention_days: 84.0,
  recommended_window: 'Next low-demand window in ~84 d (overnight 02:00-06:00, off-peak demand)',
  spares_required: ['RO elements (tail vessels)', 'CIP chemicals'],
  expected_downtime_hours: 16.0,
  maintenance_cost: 42000.0,
  avoided_failure_cost: 160000.0,
  rank_score: 26.8,
  recommendation_id: 'rec-pdm-ast-memb-01',
  control_boundary: controlBoundary,
  approval_status: 'pending' as const,
  provenance: 'preliminary' as const,
};

export const maintenanceRanking: MaintenanceRankingResponse = {
  ...pdmEnvelope,
  ranking: [pdmRecommendationHpp, pdmRecommendationMemb],
};

export const pdmCardHpp: RecommendationCard = {
  ...recommendation,
  recommendation_id: 'rec-pdm-ast-hpp-01',
  asset_id: 'AST-HPP-01',
  summary:
    "High-Pressure Pump A: predicted failure mode 'Progressive hydraulic-efficiency loss'.",
  recommended_action: 'Plan maintenance within ~34 d. Advisory only — operator approval required.',
  source_engine_status: 'predictive-maintenance: preliminary',
  approval_status: 'pending',
};

export const maintenanceRecommendations: MaintenanceRecommendationsResponse = {
  ...pdmEnvelope,
  recommendations: [pdmRecommendationHpp, pdmRecommendationMemb],
  cards: [pdmCardHpp],
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
