import type {
  Asset,
  AnomalyResult,
  AssistantExamplesResponse,
  AssistantResponse,
  AuditResponse,
  BillingExportResponse,
  ControlBoundary,
  DocumentsResponse,
  EntitlementsResponse,
  UpdateChannelResponse,
  UsageResponse,
  EnergyLossesResponse,
  EnergyOptimizeResponse,
  EnergySummaryResponse,
  EquipmentEnvelopeResponse,
  EquipmentFailureProbabilityResponse,
  EquipmentHealthResponse,
  EquipmentRootCauseResponse,
  EquipmentRulResponse,
  ExecutiveROIResponse,
  ExecutiveValueSummaryResponse,
  GridOutageResponse,
  HealthScore,
  MaintenanceRankingResponse,
  MaintenanceRecommendationsResponse,
  MembraneHealthResponse,
  PlantOverview,
  PumpCurve,
  RecommendationCard,
  ResilienceCriticalityResponse,
  ResilienceGeneratorResponse,
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

// --- Value layer: Energy / Resilience / Executive ---

const valueEnvelope = {
  facility_id: 'S3M-DESAL-01',
  train_id: 'RO-TRAIN-001',
  control_boundary: controlBoundary,
};

export const energySummary: EnergySummaryResponse = {
  ...valueEnvelope,
  provenance: 'estimated',
  energy_by_asset: [
    { asset_id: 'AST-HPP-01', name: 'High-Pressure Pump A (net of ERD)', power_kw: 520.4, provenance: 'synthetic' },
    { asset_id: 'AST-ERD-01', name: 'Energy Recovery Device (recovered)', power_kw: -260.1, provenance: 'synthetic' },
    { asset_id: 'AST-BOOST-01', name: 'Booster / Permeate Pump', power_kw: 24.0, provenance: 'synthetic' },
    { asset_id: 'AST-DOSE-01', name: 'Dosing Skid', power_kw: 6.0, provenance: 'synthetic' },
    { asset_id: 'AUX', name: 'Auxiliary / Controls', power_kw: 14.0, provenance: 'synthetic' },
  ],
  total_power_kw: 564.4,
  current_setpoint: { feed_pressure_bar: 68.0, recovery: 0.42, sec_kwh_m3: 2.58, permeate_flow_m3h: 210.0 },
  optimal_setpoint: { feed_pressure_bar: 57.0, recovery: 0.3772, sec_kwh_m3: 2.21, permeate_flow_m3h: 188.6 },
  current_sec_kwh_m3: 2.58,
  optimal_sec_kwh_m3: 2.21,
  sec_reduction_kwh_m3: 0.37,
  sec_reduction_pct: 14.3,
  estimated_cost_saving_per_day: 219.97,
  currency: 'USD',
};

export const energyOptimize: EnergyOptimizeResponse = {
  ...valueEnvelope,
  provenance: 'estimated',
  optimization: {
    asset_id: 'AST-HPP-01',
    optimal_feed_pressure_bar: 57.0,
    optimal_recovery: 0.3772,
    baseline_sec_kwh_m3: 2.58,
    optimized_sec_kwh_m3: 2.21,
    sec_reduction_kwh_m3: 0.37,
    sec_reduction_pct: 14.3,
    permeate_flow_m3h: 188.6,
    permeate_tds_mg_l: 261.1,
    permeate_boron_mg_l: 0.582,
    estimated_energy_saving_kwh_day: 2444.07,
    estimated_cost_saving_per_day: 219.97,
    currency: 'USD',
    constraints_respected: true,
    binding_constraints: [],
    method: 'scipy.optimize.minimize (bounded SLSQP) over the deterministic RO model',
    provenance: 'estimated',
  },
};

export const energyLosses: EnergyLossesResponse = {
  ...valueEnvelope,
  provenance: 'estimated',
  losses: [
    {
      label: 'RO specific-energy vs optimum',
      current_sec_kwh_m3: 2.58,
      best_achievable_sec_kwh_m3: 2.21,
      avoidable_loss_kwh_m3: 0.37,
      avoidable_loss_pct: 14.3,
      estimated_avoidable_kwh_day: 2444.07,
      estimated_avoidable_cost_per_day: 219.97,
      currency: 'USD',
      provenance: 'estimated',
    },
  ],
};

export const resilienceGenerator: ResilienceGeneratorResponse = {
  ...valueEnvelope,
  provenance: 'preliminary',
  generator: {
    generator_id: 'GEN-001',
    name: 'Standby Diesel Generator',
    start_probability: 0.94,
    battery_fraction: 0.86,
    days_since_last_test: 22,
    maintenance_due: false,
    fuel_level_fraction: 0.72,
    consumption_rate_l_per_h: 230.0,
    load_fraction: 0.85,
    fuel_endurance_hours: 13.0,
    rated_power_kw: 1100.0,
    provenance: 'preliminary',
  },
};

export const resilienceCriticality: ResilienceCriticalityResponse = {
  ...valueEnvelope,
  provenance: 'preliminary',
  criticality: [
    {
      asset_id: 'AST-HPP-01',
      asset_name: 'High-Pressure Pump A',
      criticality_score: 74.5,
      customer_or_production_impact: 0.95,
      failure_probability: 0.35,
      recovery_time_hours: 36,
      dependency_centrality: 0.95,
      backup_deficiency: 0.6,
      rank: 1,
      provenance: 'preliminary',
    },
    {
      asset_id: 'AST-BOOST-01',
      asset_name: 'Booster / Permeate Pump',
      criticality_score: 45.2,
      customer_or_production_impact: 0.55,
      failure_probability: 0.18,
      recovery_time_hours: 10,
      dependency_centrality: 0.6,
      backup_deficiency: 0.4,
      rank: 2,
      provenance: 'preliminary',
    },
  ],
};

export const gridOutage: GridOutageResponse = {
  ...valueEnvelope,
  provenance: 'preliminary',
  scenario: 'grid_outage',
  generator: resilienceGenerator.generator,
  load_shed_plan: {
    available_generation_kw: 1100.0,
    total_load_kw: 1280.0,
    retained_load_kw: 1070.0,
    shed_load_kw: 210.0,
    critical_loads_sustained: true,
    provenance: 'preliminary',
    items: [
      { asset_id: 'AST-CIP-01', asset_name: 'CIP System', load_kw: 150, priority: 'non_essential', shed_order: 1, retained: false },
      { asset_id: 'AST-AUX-01', asset_name: 'Building / Auxiliary Loads', load_kw: 60, priority: 'non_essential', shed_order: 2, retained: false },
      { asset_id: 'AST-BOOST-01', asset_name: 'Booster / Permeate Pump', load_kw: 130, priority: 'essential', shed_order: 3, retained: true },
      { asset_id: 'AST-DOSE-01', asset_name: 'Dosing Skid', load_kw: 40, priority: 'essential', shed_order: 4, retained: true },
      { asset_id: 'AST-HPP-01', asset_name: 'High-Pressure Pump A', load_kw: 900, priority: 'critical', shed_order: 5, retained: true },
    ],
  },
  service_continuity: {
    scenario: 'grid_outage',
    service_continuity_hours: 13.0,
    limiting_factor: 'generator fuel endurance',
    generator_available: true,
    generator_start_probability: 0.94,
    fuel_endurance_hours: 13.0,
    battery_bridge_minutes: 12.0,
    critical_loads_sustained: true,
    provenance: 'preliminary',
  },
  criticality: resilienceCriticality.criticality,
  recommendation: {
    ...recommendation,
    recommendation_id: 'rec-resilience-grid-outage',
    asset_id: 'AST-HPP-01',
    summary: 'Grid outage: prioritise GEN-001 to the high-pressure pump + essential loads.',
    recommended_action:
      'Prioritise GEN-001 to the HP pump (AST-HPP-01) and essential loads; shed non-essential loads. Advisory only — operator approval required, no control write.',
    source_engine_status: 'resilience: preliminary',
    approval_status: 'pending',
  },
};

export const executiveValueSummary: ExecutiveValueSummaryResponse = {
  ...valueEnvelope,
  provenance: 'estimated',
  disclaimer:
    'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes. Every figure is preliminary and advisory only.',
  value_summary: {
    facility_id: 'S3M-DESAL-01',
    train_id: 'RO-TRAIN-001',
    currency: 'USD',
    downtime_avoided: 210000.0,
    energy_savings: 80289.0,
    chemical_savings: 12600.0,
    water_loss_avoided: 3577.0,
    maintenance_savings: 140000.0,
    capex_deferred: 114000.0,
    total_annualized_benefit: 560466.0,
    synthetic_basis: true,
    disclaimer:
      'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes. Every figure is preliminary and advisory only.',
    provenance: 'estimated',
    components: [
      { category: 'downtime_avoided', annualized_benefit: 210000.0, basis: 'PdM avoided-failure cost (downtime share)', currency: 'USD', provenance: 'estimated' },
      { category: 'energy_savings', annualized_benefit: 80289.0, basis: 'RO SEC optimization daily saving × 365', currency: 'USD', provenance: 'estimated' },
      { category: 'chemical_savings', annualized_benefit: 12600.0, basis: 'antiscalant dosing headroom (best-effort)', currency: 'USD', provenance: 'estimated' },
      { category: 'water_loss_avoided', annualized_benefit: 3577.0, basis: 'reduced leakage losses (best-effort)', currency: 'USD', provenance: 'estimated' },
      { category: 'maintenance_savings', annualized_benefit: 140000.0, basis: 'PdM avoided-failure cost (repair share)', currency: 'USD', provenance: 'estimated' },
      { category: 'capex_deferred', annualized_benefit: 114000.0, basis: 'replacement value deferred by life extension', currency: 'USD', provenance: 'estimated' },
    ],
  },
};

export const executiveRoi: ExecutiveROIResponse = {
  ...valueEnvelope,
  provenance: 'estimated',
  disclaimer:
    'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes. Every figure is preliminary and advisory only.',
  roi: {
    facility_id: 'S3M-DESAL-01',
    train_id: 'RO-TRAIN-001',
    currency: 'USD',
    pilot_investment: 250000.0,
    pilot_benefit: 280233.0,
    pilot_roi_pct: 12.09,
    annualized_benefit: 560466.0,
    payback_period_months: 5.35,
    synthetic_basis: true,
    disclaimer:
      'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes. Every figure is preliminary and advisory only.',
    provenance: 'estimated',
  },
};

// --- S3M Operations Assistant ---

export const assistantExamples: AssistantExamplesResponse = {
  control_boundary: controlBoundary,
  examples: [
    { intent: 'explain_degradation', question: 'Why is HPP-001 degrading?' },
    { intent: 'scenario_impact', question: 'What happens if the high-pressure pump fails?' },
    { intent: 'optimize_energy', question: 'Which setpoint minimizes energy use?' },
    {
      intent: 'generator_priority',
      question: 'Which asset gets the generator first during a grid outage?',
    },
    {
      intent: 'show_evidence',
      question: 'Show the evidence behind the membrane cleaning recommendation.',
    },
    { intent: 'draft_work_order', question: 'Draft a work order for the high-pressure pump.' },
    { intent: 'shift_summary', question: 'Give me a shift summary for RO-TRAIN-001.' },
    { intent: 'water_quality_status', question: 'What is the current water quality status?' },
  ],
};

export const assistantAnswer: AssistantResponse = {
  query: 'Why is HPP-001 degrading?',
  intent: 'explain_degradation',
  target: 'AST-HPP-01',
  answer:
    'High-Pressure Pump A (AST-HPP-01) is at health 32/100 (Critical). Leading penalties: ' +
    'Vibration -19; Current imbalance -9. Most probable root cause: bearing wear (44%). ' +
    'Preliminary 30-day failure probability 48%; remaining useful life ~96 d. All figures are ' +
    'preliminary engineering estimates, not validated.',
  evidence: {
    telemetry_window: 'live synthetic platform telemetry (aggregated, advisory)',
    assets_reviewed: ['AST-HPP-01'],
    documents_reviewed: ['MAN-HPP-001', 'REC-MAINT-HIST-001', 'PROC-ISO-HPP-001'],
    simulation_ids: [],
    assumptions: [
      'Answer assembled from existing platform layer outputs + retrieved documents (advisory).',
      'Health is a visible-penalty score; RUL / failure probability are preliminary estimates.',
    ],
    data_timestamp: '2026-07-17T07:00:00Z',
  },
  confidence: 0.69,
  recommended_action: {
    ...recommendation,
    recommendation_id: 'rec-assistant-explain_degradation-ast-hpp-01',
    asset_id: 'AST-HPP-01',
    summary: 'High-Pressure Pump A: health 32 (Critical); 30-day failure probability 48%.',
    recommended_action:
      'Review the ranked root causes and plan maintenance ahead of the lower RUL bound. ' +
      'Advisory only — operator approval required, no control write.',
    source_engine_status: 'fallback_local',
    approval_status: 'pending',
  },
  approval_required: true,
  grounded: true,
  source_engine_status: 'fallback_local',
  provenance: 'preliminary',
  control_boundary: controlBoundary,
  packet_id: 'pkt-assistant-explain_degradation-ast-hpp-01',
  created_at: '2026-07-17T07:00:00Z',
};

export const documentsList: DocumentsResponse = {
  control_boundary: controlBoundary,
  documents: [
    {
      document_id: 'MAN-HPP-001',
      title: 'High-Pressure Feed Pump — Operation & Maintenance Manual (Excerpt)',
      document_type: 'manual',
      path: 'data/manuals/hp_pump_manual.md',
      tags: ['AST-HPP-01', 'pump', 'bearing', 'seal', 'vibration'],
    },
    {
      document_id: 'PROC-ISO-HPP-001',
      title: 'Procedure: High-Pressure Pump Isolation (Lockout/Tagout)',
      document_type: 'procedure',
      path: 'data/procedures/pump_isolation_procedure.md',
      tags: ['AST-HPP-01', 'isolation', 'pump'],
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

// --- Administration fixtures ---

export const entitlements: EntitlementsResponse = {
  control_boundary: controlBoundary,
  safety_invariant_intact: true,
  entitlements: {
    tenant_id: 'default',
    plan: 'enterprise',
    enabled_features: ['water_quality', 'energy_optimization', 'support_bundle'],
    features: {
      water_quality: { label: 'Water Quality Intelligence', enabled: true },
      energy_optimization: { label: 'Energy Optimization', enabled: true },
      signed_updates: { label: 'Signed-update channel', enabled: true },
      support_bundle: { label: 'In-app support bundles', enabled: true },
    },
    limits: {
      max_facilities: -1,
      max_assets: -1,
      max_monthly_ingest_events: -1,
    },
  },
  usage: {
    period: '2026-07',
    facilities: 2,
    assets: 5,
    ingest_events: 1200,
    api_calls: { scenario_run: 3 },
    facility_ids: ['S3M-DESAL-01', 'S3M-DESAL-02'],
    asset_ids: ['AST-HPP-01', 'AST-CF-01'],
  },
  limits_status: [
    { metric: 'facilities', used: 2, limit: -1, unlimited: true, within_limit: true },
    { metric: 'assets', used: 5, limit: -1, unlimited: true, within_limit: true },
    { metric: 'ingest_events', used: 1200, limit: -1, unlimited: true, within_limit: true },
  ],
};

export const usage: UsageResponse = {
  control_boundary: controlBoundary,
  usage: entitlements.usage,
};

export const billingExport: BillingExportResponse = {
  control_boundary: controlBoundary,
  billing_export: {
    tenant_id: 'default',
    plan: 'enterprise',
    period: '2026-07',
    generated_at: '2026-07-17T12:00:00Z',
    api_calls: { scenario_run: 3 },
    metrics: [
      { metric: 'facilities', quantity: 2, unit: 'facility', limit: -1, unlimited: true, within_limit: true },
      { metric: 'assets', quantity: 5, unit: 'asset', limit: -1, unlimited: true, within_limit: true },
      {
        metric: 'ingest_events',
        quantity: 1200,
        unit: 'reading',
        limit: -1,
        unlimited: true,
        within_limit: true,
      },
    ],
  },
};

export const updateChannel: UpdateChannelResponse = {
  control_boundary: controlBoundary,
  update_channel: {
    current_version: '0.1.0',
    channel: 'stable',
    signature_algorithm: 'ed25519',
    public_key_configured: false,
    public_key_fingerprint: null,
    auto_update_enabled: false,
    verify_before_apply: true,
    policy:
      'Updates are verified before they may be applied, and are applied manually by an operator — never automatically in production.',
    documentation: 'docs/operations/signed-updates.md',
  },
};
