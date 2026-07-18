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

// Mirrors packages/canonical_water_model DataProvenance. The `vendor_specified`,
// `customer_supplied` and `customer_measured` members describe values that came
// from a customer file (OEM datasheet, customer document, or customer historian/
// LIMS export) and must never be confused with live `measured` telemetry.
export type DataProvenance =
  | 'synthetic'
  | 'simulated'
  | 'preliminary'
  | 'estimated'
  | 'vendor_specified'
  | 'customer_supplied'
  | 'customer_measured'
  | 'measured';

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

// --- Water Quality Intelligence (advisory, preliminary) ---

export type SampleType = 'continuous' | 'lab';
export type QCStatus = 'pass' | 'warn' | 'fail' | 'pending';

export interface WQEnvelope {
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
}

export interface WQComplianceCheck {
  variable: string;
  value: number;
  limit: number;
  within_limit: boolean;
}

export interface WQStageStatus {
  stage: string;
  location: string;
  compliance: WQComplianceCheck[];
  provenance: DataProvenance;
  recovery?: number;
  salt_rejection?: number;
  salt_passage?: number;
}

export interface WQSample {
  sample_id: string;
  sampling_point_id: string;
  stage: string;
  stream_id?: string | null;
  timestamp: string;
  provenance: DataProvenance;
  measurements: Record<string, number>;
  sample_type: SampleType;
  method?: string | null;
  detection_limit?: number | null;
  limit?: number | null;
  qc_status: QCStatus;
}

export interface WQSummary {
  recovery: number;
  salt_rejection: number;
  salt_passage: number;
  normalized_salt_passage: number;
  normalized_dp_bar: number;
  permeate_tds_mg_l: number;
  permeate_boron_mg_l: number;
}

export interface WQStatusResponse extends WQEnvelope {
  stage_status: WQStageStatus[];
  samples: WQSample[];
  summary: WQSummary;
}

export interface ContaminantMatrixRow {
  contaminant: string;
  unit: string;
  intake?: number | null;
  post_pretreatment?: number | null;
  ro_feed?: number | null;
  permeate?: number | null;
  finished?: number | null;
  brine?: number | null;
  removal_pct?: number | null;
  limit?: number | null;
  provenance: DataProvenance;
}

export interface WQContaminantMatrixResponse extends WQEnvelope {
  rows: ContaminantMatrixRow[];
}

export interface WQRemovalRow {
  contaminant: string;
  unit: string;
  current_pct: number | null;
  design_pct: number;
  predicted_pct: number | null;
  confidence: number;
  provenance: DataProvenance;
}

export interface WQRemovalResponse extends WQEnvelope {
  removal: WQRemovalRow[];
}

export interface ScalingRisk {
  compound: string;
  saturation: number;
  probability: number;
  ro_stage_at_risk?: string | null;
  max_safe_recovery?: number | null;
  recommended_antiscalant_note?: string | null;
  provenance: DataProvenance;
}

export interface WQScalingResponse extends WQEnvelope {
  scaling: ScalingRisk[];
}

export interface WaterQualityForecast {
  target: string;
  unit: string;
  horizon: string;
  predicted_value: number;
  lower: number;
  upper: number;
  confidence: number;
  basis?: string | null;
  provenance: DataProvenance;
}

export interface WQForecastResponse extends WQEnvelope {
  forecasts: WaterQualityForecast[];
}

export interface WQAlert {
  code: string;
  stage?: string | null;
  cause: string;
  horizon?: string | null;
  confidence: number;
  recommended_action: string;
  approval_required: boolean;
  provenance: DataProvenance;
}

export interface WQAlertsResponse extends WQEnvelope {
  alerts: WQAlert[];
  recommendations: RecommendationCard[];
}

// --- Equipment & Membrane Intelligence + Predictive Maintenance (preliminary) ---

export interface PdMEnvelope {
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
}

export interface ComponentHealth {
  asset_id: string;
  component_type: string;
  score: number;
  band: HealthBand;
  contributions: HealthContribution[];
  provenance: DataProvenance;
}

export interface OperatingEnvelope {
  asset_id: string;
  samples: number;
  at_bep_fraction: number;
  low_flow_fraction: number;
  high_pressure_fraction: number;
  excess_temperature_fraction: number;
  cavitation_risk_fraction: number;
  provenance: DataProvenance;
}

export interface RemainingUsefulLife {
  asset_id: string;
  rul_days: number;
  lower_days: number;
  upper_days: number;
  method: string;
  basis: string[];
  provenance: DataProvenance;
}

export interface FailureProbability {
  asset_id: string;
  horizons: Record<string, number>;
  predicted_failure_mode?: string | null;
  provenance: DataProvenance;
}

export interface MaintenancePriority {
  asset_id: string;
  rank_score: number;
  factors: Record<string, number>;
  provenance: DataProvenance;
}

export interface RootCauseRanking {
  asset_id: string;
  ranked_causes: RankedCause[];
  provenance: DataProvenance;
}

export interface FoulingSeverity {
  organic: number;
  colloidal: number;
  biological: number;
  scaling: number;
}

export interface MembraneHealth {
  asset_id: string;
  score: number;
  band: HealthBand;
  normalized_permeate_flow_decline_pct: number;
  normalized_salt_passage_rise_pct: number;
  normalized_dp_rise_pct: number;
  fouling: FoulingSeverity;
  salt_passage_trend_pct_per_day: number;
  cleaning_required: boolean;
  cleaning_reason?: string | null;
  underperforming_vessel?: string | null;
  rul?: RemainingUsefulLife | null;
  contributions: HealthContribution[];
  provenance: DataProvenance;
}

export interface PdMRecommendation {
  asset_id: string;
  asset_name?: string | null;
  predicted_failure_mode: string;
  failure_probability_30d: number;
  rul_days: number;
  rul_lower_days: number;
  rul_upper_days: number;
  time_to_intervention_days: number;
  recommended_window: string;
  spares_required: string[];
  expected_downtime_hours: number;
  maintenance_cost: number;
  avoided_failure_cost: number;
  rank_score: number;
  recommendation_id?: string | null;
  control_boundary: ControlBoundary;
  approval_status: ApprovalStatus;
  provenance: DataProvenance;
}

export interface EquipmentHealthResponse extends PdMEnvelope {
  health: ComponentHealth;
}

export interface EquipmentRulResponse extends PdMEnvelope {
  rul: RemainingUsefulLife;
}

export interface EquipmentFailureProbabilityResponse extends PdMEnvelope {
  failure_probability: FailureProbability;
}

export interface EquipmentEnvelopeResponse extends PdMEnvelope {
  envelope: OperatingEnvelope;
}

export interface EquipmentRootCauseResponse extends PdMEnvelope {
  root_cause: RootCauseRanking;
}

export interface MembraneHealthResponse extends PdMEnvelope {
  membrane: MembraneHealth;
}

export interface MaintenanceRankingResponse extends PdMEnvelope {
  ranking: PdMRecommendation[];
}

export interface MaintenanceRecommendationsResponse extends PdMEnvelope {
  recommendations: PdMRecommendation[];
  cards: RecommendationCard[];
}

// --- Work orders / Maintenance Center (advisory, preliminary) ---

export type WorkOrderStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'open'
  | 'in_progress'
  | 'completed'
  | 'cancelled';

export type WorkOrderPriority = 'low' | 'medium' | 'high' | 'urgent';

export type WorkOrderSource = 'predictive_maintenance' | 'cmms' | 'manual';

export type CmmsSyncStatus = 'not_synced' | 'synced' | 'failed';

export interface MaintenanceWorkOrder {
  work_order_id: string;
  asset_id: string;
  asset_name?: string | null;
  title: string;
  description: string;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  source: WorkOrderSource;
  originating_model?: string | null;
  source_recommendation_id?: string | null;
  source_alert_code?: string | null;
  predicted_failure_mode?: string | null;
  failure_probability_30d?: number | null;
  rul_days?: number | null;
  recommended_window?: string | null;
  spares_required: string[];
  estimated_downtime_hours?: number | null;
  estimated_cost?: number | null;
  ranked_causes: RankedCause[];
  evidence?: Evidence | null;
  approval_status: ApprovalStatus;
  approved_by?: string | null;
  decided_at?: string | null;
  cmms_system?: string | null;
  cmms_external_id?: string | null;
  cmms_sync_status: CmmsSyncStatus;
  control_boundary: ControlBoundary;
  provenance: DataProvenance;
  created_at: string;
}

export interface AssetMaintenanceRecord {
  work_order_id: string;
  asset_id: string;
  title: string;
  status: WorkOrderStatus;
  performed_at?: string | null;
  performed_by?: string | null;
  labor_hours?: number | null;
  cost?: number | null;
  notes?: string | null;
  cmms_system?: string | null;
  provenance: DataProvenance;
}

export interface CmmsDescription {
  kind: string;
  name: string;
  write_enabled: boolean;
  read_only: boolean;
  write_back_is_control_path: boolean;
  operator_approval_required: boolean;
}

export interface WorkOrdersResponse extends PdMEnvelope {
  work_orders: MaintenanceWorkOrder[];
}

export interface WorkOrderResponse extends PdMEnvelope {
  work_order: MaintenanceWorkOrder;
}

export interface CmmsStatusResponse extends PdMEnvelope {
  cmms: CmmsDescription;
}

export interface CmmsWorkOrdersResponse extends PdMEnvelope {
  cmms: CmmsDescription;
  work_orders: MaintenanceWorkOrder[];
}

export interface CmmsAssetHistoryResponse extends PdMEnvelope {
  cmms: CmmsDescription;
  asset_id: string;
  history: AssetMaintenanceRecord[];
}

export interface WorkOrderDecisionRequest {
  status: 'approved' | 'rejected';
  actor?: string;
}

// --- Value layer: Energy / Resilience / Executive (estimated, preliminary) ---

export interface ValueEnvelope {
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
}

export interface EnergyByAsset {
  asset_id: string;
  name: string;
  power_kw: number;
  provenance: DataProvenance;
}

export interface EnergySetpoint {
  feed_pressure_bar: number;
  recovery: number;
  sec_kwh_m3: number;
  permeate_flow_m3h: number;
}

export interface EnergySummaryResponse extends ValueEnvelope {
  energy_by_asset: EnergyByAsset[];
  total_power_kw: number;
  current_setpoint: EnergySetpoint;
  optimal_setpoint: EnergySetpoint;
  current_sec_kwh_m3: number;
  optimal_sec_kwh_m3: number;
  sec_reduction_kwh_m3: number;
  sec_reduction_pct: number;
  estimated_cost_saving_per_day: number;
  currency: string;
}

export interface EnergyOptimizationResult {
  asset_id?: string | null;
  optimal_feed_pressure_bar: number;
  optimal_recovery: number;
  baseline_sec_kwh_m3: number;
  optimized_sec_kwh_m3: number;
  sec_reduction_kwh_m3: number;
  sec_reduction_pct: number;
  permeate_flow_m3h: number;
  permeate_tds_mg_l: number;
  permeate_boron_mg_l: number;
  estimated_energy_saving_kwh_day: number;
  estimated_cost_saving_per_day: number;
  currency: string;
  constraints_respected: boolean;
  binding_constraints: string[];
  method: string;
  provenance: DataProvenance;
}

export interface EnergyOptimizeResponse extends ValueEnvelope {
  optimization: EnergyOptimizationResult;
}

export interface EnergyLoss {
  label: string;
  current_sec_kwh_m3: number;
  best_achievable_sec_kwh_m3: number;
  avoidable_loss_kwh_m3: number;
  avoidable_loss_pct: number;
  estimated_avoidable_kwh_day: number;
  estimated_avoidable_cost_per_day: number;
  currency: string;
  provenance: DataProvenance;
}

export interface EnergyLossesResponse extends ValueEnvelope {
  losses: EnergyLoss[];
}

export interface ResilienceCriticality {
  asset_id: string;
  asset_name?: string | null;
  criticality_score: number;
  customer_or_production_impact: number;
  failure_probability: number;
  recovery_time_hours: number;
  dependency_centrality: number;
  backup_deficiency: number;
  rank?: number | null;
  provenance: DataProvenance;
}

export interface ResilienceCriticalityResponse extends ValueEnvelope {
  criticality: ResilienceCriticality[];
}

export interface GeneratorStatus {
  generator_id: string;
  name?: string | null;
  start_probability: number;
  battery_fraction: number;
  days_since_last_test: number;
  maintenance_due: boolean;
  fuel_level_fraction: number;
  consumption_rate_l_per_h: number;
  load_fraction: number;
  fuel_endurance_hours: number;
  rated_power_kw?: number | null;
  provenance: DataProvenance;
}

export interface ResilienceGeneratorResponse extends ValueEnvelope {
  generator: GeneratorStatus;
}

export interface LoadShedItem {
  asset_id: string;
  asset_name?: string | null;
  load_kw: number;
  priority: string;
  shed_order: number;
  retained: boolean;
}

export interface LoadShedPlan {
  available_generation_kw: number;
  total_load_kw: number;
  retained_load_kw: number;
  shed_load_kw: number;
  items: LoadShedItem[];
  critical_loads_sustained: boolean;
  provenance: DataProvenance;
}

export interface ServiceContinuity {
  scenario: string;
  service_continuity_hours: number;
  limiting_factor: string;
  generator_available: boolean;
  generator_start_probability: number;
  fuel_endurance_hours: number;
  battery_bridge_minutes: number;
  critical_loads_sustained: boolean;
  provenance: DataProvenance;
}

export interface GridOutageResponse extends ValueEnvelope {
  scenario: string;
  generator: GeneratorStatus;
  load_shed_plan: LoadShedPlan;
  service_continuity: ServiceContinuity;
  criticality: ResilienceCriticality[];
  recommendation: RecommendationCard;
}

export interface ValueComponent {
  category: string;
  annualized_benefit: number;
  basis: string;
  currency: string;
  provenance: DataProvenance;
}

export interface ExecutiveValueSummary {
  facility_id: string;
  train_id: string;
  currency: string;
  downtime_avoided: number;
  energy_savings: number;
  chemical_savings: number;
  water_loss_avoided: number;
  maintenance_savings: number;
  capex_deferred: number;
  total_annualized_benefit: number;
  components: ValueComponent[];
  synthetic_basis: boolean;
  disclaimer: string;
  provenance: DataProvenance;
}

export interface ExecutiveValueSummaryResponse extends ValueEnvelope {
  value_summary: ExecutiveValueSummary;
  disclaimer: string;
}

export interface ROIEstimate {
  facility_id: string;
  train_id: string;
  currency: string;
  pilot_investment: number;
  pilot_benefit: number;
  pilot_roi_pct: number;
  annualized_benefit: number;
  payback_period_months: number;
  synthetic_basis: boolean;
  disclaimer: string;
  provenance: DataProvenance;
}

export interface ExecutiveROIResponse extends ValueEnvelope {
  roi: ROIEstimate;
  disclaimer: string;
}

// --- S3M Operations Assistant (advisory, grounded) ---

export type DocumentType = 'manual' | 'procedure' | 'maintenance_record';

export interface DocumentRef {
  document_id: string;
  title: string;
  document_type: DocumentType;
  path: string;
  tags: string[];
  score?: number | null;
  snippet?: string | null;
}

export interface DocumentsResponse {
  documents: DocumentRef[];
  control_boundary: ControlBoundary;
}

export interface AssistantResponse {
  query: string;
  intent: string;
  target?: string | null;
  answer: string;
  evidence: Evidence;
  confidence: number;
  recommended_action?: RecommendationCard | null;
  approval_required: boolean;
  grounded: boolean;
  source_engine_status: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
  packet_id?: string | null;
  created_at: string;
}

export interface AssistantExample {
  intent: string;
  question: string;
}

export interface AssistantExamplesResponse {
  examples: AssistantExample[];
  control_boundary: ControlBoundary;
}

// --- Administration: licensing, metering, updates, support ---
// Commercial-hardening administration. Feature-gating is a product-packaging
// concern only; it never touches the advisory/read-only control boundary.

export interface EntitlementFeature {
  label: string;
  enabled: boolean;
}

export interface Entitlements {
  tenant_id: string;
  plan: string;
  features: Record<string, EntitlementFeature>;
  enabled_features: string[];
  limits: Record<string, number>;
}

export interface LimitStatus {
  metric: string;
  used: number;
  limit: number;
  unlimited: boolean;
  within_limit: boolean;
}

export interface EntitlementsResponse {
  entitlements: Entitlements;
  usage: UsageSnapshot;
  limits_status: LimitStatus[];
  safety_invariant_intact: boolean;
  control_boundary: ControlBoundary;
}

export interface UsageSnapshot {
  period: string;
  facilities: number;
  assets: number;
  ingest_events: number;
  api_calls: Record<string, number>;
  facility_ids: string[];
  asset_ids: string[];
}

export interface UsageResponse {
  usage: UsageSnapshot;
  control_boundary: ControlBoundary;
}

export interface BillingMetric {
  metric: string;
  quantity: number;
  unit: string;
  limit: number;
  unlimited: boolean;
  within_limit: boolean;
}

export interface BillingExport {
  tenant_id: string;
  plan: string;
  period: string;
  generated_at: string;
  metrics: BillingMetric[];
  api_calls: Record<string, number>;
}

export interface BillingExportResponse {
  billing_export: BillingExport;
  control_boundary: ControlBoundary;
}

export interface UpdateChannel {
  current_version: string;
  channel: string;
  signature_algorithm: string;
  public_key_configured: boolean;
  public_key_fingerprint?: string | null;
  auto_update_enabled: boolean;
  verify_before_apply: boolean;
  policy: string;
  documentation: string;
}

export interface UpdateChannelResponse {
  update_channel: UpdateChannel;
  control_boundary: ControlBoundary;
}

export interface UpdateVerification {
  verified: boolean;
  reason: string;
  algorithm: string;
  fingerprint?: string | null;
  manifest_version?: string | null;
  applied: boolean;
}

export interface UpdateVerifyResponse {
  verification: UpdateVerification;
  applied: boolean;
  note: string;
  control_boundary: ControlBoundary;
}

// --- Network Twin (GeoJSON topology + C1 leak-localization overlay) ---

// Minimal GeoJSON shapes (lon, lat). Kept local so the dashboard does not take
// a hard dependency on @types/geojson for a small, well-defined surface.
export type GeoPosition = [number, number];

export interface GeoPoint {
  type: 'Point';
  coordinates: GeoPosition;
}

export interface GeoLineString {
  type: 'LineString';
  coordinates: GeoPosition[];
}

export interface GeoPolygon {
  type: 'Polygon';
  coordinates: GeoPosition[][];
}

export interface GeoFeature<G, P> {
  type: 'Feature';
  geometry: G;
  properties: P;
  id?: string | number;
}

export interface GeoFeatureCollection<F> {
  type: 'FeatureCollection';
  features: F[];
}

export type NetworkElementType =
  | 'pipe'
  | 'junction'
  | 'valve'
  | 'pump'
  | 'tank'
  | 'reservoir';

export interface NetworkElementProperties {
  element_id: string;
  element_type: NetworkElementType;
  label: string;
  // When present, links a rendered element to a canonical asset so operators can
  // click through to its Asset Twin.
  asset_id?: string | null;
  treatment_stage?: TreatmentStage | null;
}

export type NetworkNodeFeature = GeoFeature<GeoPoint, NetworkElementProperties>;
export type NetworkLinkFeature = GeoFeature<GeoLineString, NetworkElementProperties>;
export type NetworkFeature = NetworkNodeFeature | NetworkLinkFeature;

export interface NetworkResponse {
  network_id: string;
  facility_id: string;
  train_id: string;
  engine: string;
  provenance: DataProvenance;
  features: NetworkFeature[];
}

export interface LeakCandidateZoneProperties {
  zone_id: string;
  rank: number;
  suspected_node_id: string;
  // Model likelihood (0..1) that the leak is inside this candidate zone.
  likelihood: number;
  residual_pressure_m: number;
  // C1 leak-localization output is always preliminary/synthetic — never a
  // validated, confirmed leak location.
  synthetic: boolean;
  provenance: DataProvenance;
}

export type LeakCandidateZoneFeature = GeoFeature<GeoPolygon, LeakCandidateZoneProperties>;

export interface LeakLocalizationResponse {
  network_id: string;
  method: string;
  // True while the localization is a preliminary/synthetic estimate.
  preliminary: boolean;
  provenance: DataProvenance;
  candidate_zones: LeakCandidateZoneFeature[];
}

// --- Administration / Configuration Workbench (A1: /api/v1/config) ---
//
// Mirrors the configuration document served by the /api/v1/config API. The
// document is versioned and moves through a draft -> submitted -> approved
// lifecycle. Editing and approval are RBAC-gated (admin only); everyone else
// gets a read-only view.

export type ConfigStatus = 'draft' | 'submitted' | 'approved' | 'rejected';

export interface AssetHierarchyNode {
  asset_id: string;
  name: string;
  asset_type: AssetType;
  parent_id?: string | null;
  treatment_stage?: TreatmentStage | null;
  criticality: Criticality;
}

/** Customer OT tag -> canonical asset_id.metric mapping (with unit/scale/offset/sampling). */
export interface TagMapping {
  customer_tag: string;
  asset_id: string;
  metric: string;
  unit: string;
  scale: number;
  offset: number;
  sampling_interval_s: number;
  provenance: DataProvenance;
}

export interface AlarmThreshold {
  id: string;
  asset_id: string;
  metric: string;
  unit: string;
  warn_low?: number | null;
  warn_high?: number | null;
  alarm_low?: number | null;
  alarm_high?: number | null;
  enabled: boolean;
}

export type RatedEquipmentType = 'pump' | 'membrane';

export interface RatedPumpCurvePoint {
  flow_m3h: number;
  head_m: number;
  efficiency_pct: number;
}

export interface RatedMembraneModel {
  model: string;
  element_area_m2: number;
  elements_per_vessel: number;
  nominal_salt_rejection_pct: number;
  max_feed_pressure_bar: number;
}

export interface RatedEquipment {
  asset_id: string;
  name: string;
  equipment_type: RatedEquipmentType;
  pump_curve?: RatedPumpCurvePoint[] | null;
  membrane_model?: RatedMembraneModel | null;
}

export interface ProcessStage {
  stage_id: string;
  name: string;
  order: number;
  description: string;
}

export interface SamplingPoint {
  sampling_point_id: string;
  stage: string;
  stream_id?: string | null;
  description: string;
  sample_type: SampleType;
}

export interface LabMethod {
  method_id: string;
  name: string;
  analyte: string;
  technique: string;
  detection_limit: number;
  unit: string;
}

export interface ComplianceLimit {
  id: string;
  analyte: string;
  limit: number;
  unit: string;
  basis: string;
  stage?: string | null;
}

export interface UserRoleAssignment {
  username: string;
  roles: string[];
}

export interface ConfigDocument {
  version: number;
  status: ConfigStatus;
  updated_at: string;
  updated_by: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
  asset_hierarchy: AssetHierarchyNode[];
  tag_mappings: TagMapping[];
  alarm_thresholds: AlarmThreshold[];
  rated_equipment: RatedEquipment[];
  process_stages: ProcessStage[];
  sampling_points: SamplingPoint[];
  lab_methods: LabMethod[];
  compliance_limits: ComplianceLimit[];
  user_roles: UserRoleAssignment[];
}

export interface ConfigVersionEntry {
  version: number;
  status: ConfigStatus;
  created_at: string;
  author: string;
  submitted_by?: string | null;
  approved_by?: string | null;
  note?: string | null;
}

export interface ConfigVersionsResponse {
  versions: ConfigVersionEntry[];
  control_boundary: ControlBoundary;
}

/** Editable slice of the config document (everything except server-owned metadata). */
export type ConfigDraftPayload = Pick<
  ConfigDocument,
  | 'asset_hierarchy'
  | 'tag_mappings'
  | 'alarm_thresholds'
  | 'rated_equipment'
  | 'process_stages'
  | 'sampling_points'
  | 'lab_methods'
  | 'compliance_limits'
  | 'user_roles'
>;

export interface ConfigActionRequest {
  actor?: string;
  note?: string | null;
}

// --- Model governance registry (D1/D2 governance) ---

export type DriftStatus = 'stable' | 'watch' | 'drifting' | 'unknown';

export interface ModelSpec {
  inputs: string[];
  outputs: string[];
  method: string;
  assumptions: string[];
}

export interface ModelMetric {
  name: string;
  value: number;
  unit?: string | null;
  reference?: number | null;
  drift_pct?: number | null;
}

export interface ModelRegistryEntry {
  model_id: string;
  name: string;
  version: string;
  track: string;
  description: string;
  engine: string;
  spec: ModelSpec;
  current_metrics: ModelMetric[];
  drift_status: DriftStatus;
  drift_detail?: string | null;
  validation_status: string;
  owner: string;
  last_evaluated: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
}

export interface ModelsResponse {
  models: ModelRegistryEntry[];
  count: number;
  control_boundary: ControlBoundary;
}

// --- Regulatory compliance (A1 config store) ---

export type LimitBound = 'max' | 'min';

export interface RegulatoryComplianceLimit {
  parameter: string;
  display_name: string;
  unit: string;
  limit: number;
  bound: LimitBound;
  stage: string;
  basis: string;
  enabled: boolean;
}

export interface ComplianceLimitsResponse {
  limits: RegulatoryComplianceLimit[];
  count: number;
  control_boundary: ControlBoundary;
}

export interface ComplianceCheck {
  parameter: string;
  display_name: string;
  unit: string;
  stage: string;
  value: number;
  limit: number;
  bound: LimitBound;
  within_limit: boolean;
  exceedance_pct: number;
  basis: string;
}

export type ComplianceExceedance = ComplianceCheck;

export interface ComplianceStatusResponse {
  facility_id: string;
  train_id: string;
  generated_at: string;
  scenario_fouling?: number | null;
  checks: ComplianceCheck[];
  exceedances: ComplianceExceedance[];
  compliant: boolean;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
  disclaimer: string;
}

// --- Cyber-Physical Security (advisory, read-only) ---

export type SecurityStatus = 'ok' | 'attention' | 'alert';
export type ConfidenceBand = 'high' | 'medium' | 'low';
export type ConsistencyStatus = 'consistent' | 'deviation' | 'inconsistent';

export interface SensorConfidenceRow {
  asset_id: string;
  asset_name: string;
  confidence: number;
  band: ConfidenceBand;
  cross_sensor_consistency: number;
  physical_plausibility: number;
  calibration_days: number;
}

export interface ConsistencyCheck {
  metric: string;
  observed: number;
  expected_bound: number;
  bound: 'max' | 'min';
  residual_pct: number;
  consistent: boolean;
  basis: string;
}

export interface CyberPhysicalConsistencyRow {
  asset_id: string;
  asset_name: string;
  consistency_score: number;
  status: ConsistencyStatus;
  checks: ConsistencyCheck[];
  inconsistent_metrics: string[];
}

export interface SourceHealth {
  status: 'healthy' | 'degraded' | 'unknown';
  active_source?: string | null;
  requested_source?: string | null;
  fallback: boolean;
  fallback_reason?: string | null;
  available_sources: string[];
  detail: Record<string, unknown>;
  reading_count?: number | null;
}

export interface AuditIntegrity {
  ok: boolean;
  count: number;
  head?: string;
  broken_at?: string;
  index?: number;
  reason?: string;
}

export interface SecurityOverviewResponse {
  status: SecurityStatus;
  sensor_confidence: SensorConfidenceRow[];
  cyber_physical_consistency: CyberPhysicalConsistencyRow[];
  source_health: SourceHealth;
  audit_integrity: AuditIntegrity;
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
}

export interface SiemExportRecord {
  seq: number;
  id: string;
  ts: string;
  kind: string;
  actor: string;
  subject?: string | null;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface SiemExportResponse {
  export_format: 'json';
  source: string;
  generated_at: string;
  append_only: boolean;
  record_count: number;
  chain: {
    verified: boolean;
    head: string;
    verify: AuditIntegrity;
  };
  records: SiemExportRecord[];
  signature: {
    alg: string;
    value: string;
    signed_fields: string[];
    detail: string;
  };
}

// --- Operator Training Simulator (SIMULATION, sandboxed, read-only) ---

export type TrainingScenarioType =
  | 'pump_degradation'
  | 'leak'
  | 'outage'
  | 'storm_power_loss';

export interface TrainingRubricItem {
  key: string;
  prompt: string;
  guidance: string;
  weight: number;
}

export interface TrainingScenario {
  scenario_id: string;
  scenario_type: TrainingScenarioType;
  title: string;
  category: string;
  difficulty: string;
  briefing: string;
  derived_from: string;
  learning_objectives: string[];
  rubric: TrainingRubricItem[];
}

export interface CapturedAction {
  action_id: string;
  kind: string;
  text: string;
  rubric_key?: string | null;
  approved?: boolean | null;
  sandboxed: boolean;
  emitted_command: boolean;
  recorded_at: string;
}

export interface TrainingSession {
  session_id: string;
  scenario_id: string;
  scenario: TrainingScenario;
  operator: string;
  status: string;
  simulation: boolean;
  twin_summary: {
    headline?: string;
    observed?: Record<string, number | boolean | null>;
    affected_asset?: string;
    reused_scenario?: string;
  };
  injected_telemetry: TelemetryReading[];
  actions: CapturedAction[];
  started_at: string;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
  disclaimer: string;
}

export interface ScoredItem {
  key: string;
  prompt: string;
  weight: number;
  matched: boolean;
  awarded: number;
  feedback: string;
}

export interface TrainingScore {
  total_score: number;
  max_score: number;
  percentage: number;
  band: string;
  passed: boolean;
  items: ScoredItem[];
  provenance: DataProvenance;
}

export interface TrainingRecord {
  record_id: string;
  session_id: string;
  scenario_id: string;
  scenario_title: string;
  operator: string;
  score: TrainingScore;
  actions: CapturedAction[];
  started_at: string;
  completed_at: string;
  simulation: boolean;
  provenance: DataProvenance;
  control_boundary: ControlBoundary;
  disclaimer: string;
}

interface TrainingEnvelope {
  facility_id: string;
  train_id: string;
  provenance: DataProvenance;
  simulation: boolean;
  disclaimer: string;
  control_boundary: ControlBoundary;
}

export interface TrainingScenariosResponse extends TrainingEnvelope {
  scenarios: TrainingScenario[];
}

export interface TrainingSessionResponse extends TrainingEnvelope {
  session: TrainingSession;
}

export interface TrainingActionResponse extends TrainingEnvelope {
  action: CapturedAction;
  session: TrainingSession;
}

export interface TrainingRecordResponse extends TrainingEnvelope {
  record: TrainingRecord;
}

export interface TrainingRecordsResponse extends TrainingEnvelope {
  records: TrainingRecord[];
}

export interface TrainingActionRequest {
  kind: string;
  text: string;
  rubric_key?: string | null;
  approved?: boolean | null;
}
