// TypeScript mirrors of the canonical water model (packages/canonical_water_model).
// Keep these in sync with the Pydantic definitions consumed from the API.

export type AssetType =
  | 'intake_pump'
  | 'transfer_pump'
  | 'hp_pump'
  | 'booster_pump'
  | 'permeate_pump'
  | 'brine_pump'
  | 'dosing_pump'
  | 'motor'
  | 'vfd'
  | 'erd'
  | 'cartridge_filter'
  | 'control_valve'
  | 'membrane_array'
  | 'transformer'
  | 'generator'
  | 'sensor';

export type TreatmentStage =
  | 'intake'
  | 'screening'
  | 'pretreatment'
  | 'media_filtration'
  | 'cartridge_filtration'
  | 'dosing'
  | 'high_pressure_pumping'
  | 'ro_stage_1'
  | 'ro_stage_2'
  | 'permeate'
  | 'remineralization'
  | 'disinfection'
  | 'finished_water'
  | 'distribution_handoff'
  | 'concentrate_discharge';

export type StreamType =
  | 'seawater_feed'
  | 'pretreated_feed'
  | 'ro_feed'
  | 'permeate'
  | 'concentrate'
  | 'product_water';

export type Criticality = 'low' | 'medium' | 'high' | 'critical';

export type HealthBand = 'Healthy' | 'Monitor' | 'Degraded' | 'HighRisk' | 'Critical';

export type AnomalyDomain =
  | 'mechanical'
  | 'hydraulic'
  | 'electrical'
  | 'process'
  | 'membrane'
  | 'water_quality'
  | 'sensor'
  | 'cyber_physical';

export type DataProvenance = 'synthetic' | 'simulated' | 'preliminary' | 'measured';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface RatedData {
  rated_flow_m3h?: number | null;
  rated_head_m?: number | null;
  rated_power_kw?: number | null;
  rated_speed_rpm?: number | null;
  bep_flow_m3h?: number | null;
  min_flow_m3h?: number | null;
  max_flow_m3h?: number | null;
  temp_limit_c?: number | null;
  vibration_limit_mm_s?: number | null;
}

export interface Asset {
  asset_id: string;
  name: string;
  asset_type: AssetType;
  facility_id: string;
  train_id: string;
  treatment_stage?: TreatmentStage | null;
  parent_id?: string | null;
  manufacturer: string;
  model: string;
  serial_number: string;
  location: string;
  criticality: Criticality;
  rated: RatedData;
  install_date?: string | null;
}

export interface WaterStream {
  stream_id: string;
  stream_type: StreamType;
  from_stage: TreatmentStage;
  to_stage: TreatmentStage;
  description: string;
}

export interface TelemetryReading {
  asset_id: string;
  metric: string;
  value: number;
  unit: string;
  timestamp: string;
  provenance: DataProvenance;
  quality?: string | null;
}

export interface HealthContribution {
  factor: string;
  delta: number;
  detail: string;
}

export interface HealthScore {
  asset_id: string;
  score: number;
  band: HealthBand;
  contributions: HealthContribution[];
  provenance: DataProvenance;
}

export type RankedDomain = [AnomalyDomain, number];

export interface AnomalyResult {
  asset_id: string;
  score: number;
  ranked_domains: RankedDomain[];
  factors: Record<string, number>;
  provenance: DataProvenance;
}

export interface ControlBoundary {
  control_mode: string;
  operator_approval_required: boolean;
  control_write_enabled: boolean;
}

export interface Evidence {
  telemetry_window: string;
  assets_reviewed: string[];
  documents_reviewed: string[];
  simulation_ids: string[];
  assumptions: string[];
  data_timestamp: string;
}

export interface RankedCause {
  cause: string;
  probability: number;
  evidence: string;
}

export interface RecommendationCard {
  recommendation_id: string;
  packet_id: string;
  facility_id: string;
  train_id: string;
  asset_id?: string | null;
  treatment_stage?: TreatmentStage | null;
  summary: string;
  ranked_causes: RankedCause[];
  recommended_action: string;
  confidence: number;
  evidence: Evidence;
  control_boundary: ControlBoundary;
  approval_status: ApprovalStatus;
  source_engine_status: string;
  created_at: string;
}

// --- Aggregate / composite payloads (dashboard-specific views) ---

export interface ProvenanceValue<T = number> {
  value: T;
  provenance: DataProvenance;
}

export interface PlantHealth {
  score: number;
  band: HealthBand;
  provenance: DataProvenance;
}

export interface ProductionSummary {
  permeate_flow_m3h: number;
  product_m3_per_day: number;
  feed_flow_m3h: number;
  provenance: DataProvenance;
}

export interface EnergySummary {
  total_power_kw: number;
  specific_energy_kwh_m3: number;
  provenance: DataProvenance;
}

export interface AssetStatusSummary {
  asset_id: string;
  health: number | null;
  band: HealthBand | null;
  anomaly?: number;
  normalized_salt_passage_pct?: number;
  provenance: DataProvenance;
}

export interface Alarm {
  asset_id: string;
  asset_name: string;
  severity: string;
  message: string;
  provenance: DataProvenance;
}

export interface RiskSummary {
  score: number;
  band: string;
  provenance: DataProvenance;
}

export interface PlantOverview {
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  plant_health: PlantHealth;
  production: ProductionSummary;
  recovery_pct: ProvenanceValue;
  permeate_conductivity_us_cm: ProvenanceValue;
  energy: EnergySummary;
  hp_pump_status: AssetStatusSummary;
  membrane_status: AssetStatusSummary;
  active_alarms: Alarm[];
  active_recommendations: RecommendationCard[];
  service_continuity_risk: RiskSummary;
}

export interface PumpCurvePoint {
  flow_m3h: number;
  head_m: number;
  efficiency_pct: number;
}

export interface PumpCurve {
  asset_id: string;
  supported: boolean;
  provenance: DataProvenance;
  bep?: { flow_m3h: number; head_m: number };
  operating_point?: { flow_m3h: number; head_m: number };
  curve?: PumpCurvePoint[];
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  action: string;
  recommendation_id?: string;
  asset_id?: string | null;
  actor?: string;
  note?: string;
  detail?: string;
}

export interface AuditResponse {
  provenance: DataProvenance;
  entries: AuditEntry[];
}

export interface DecisionRequest {
  operator?: string;
  note?: string | null;
}
