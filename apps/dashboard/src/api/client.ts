// Typed fetch wrappers for every /api/v1 endpoint consumed by the dashboard.

import type {
  AnomalyResult,
  Asset,
  AuditResponse,
  ControlBoundary,
  DecisionRequest,
  EquipmentEnvelopeResponse,
  EquipmentFailureProbabilityResponse,
  EquipmentHealthResponse,
  EquipmentRootCauseResponse,
  EnergyLossesResponse,
  EnergyOptimizeResponse,
  EnergySummaryResponse,
  EquipmentRulResponse,
  ExecutiveROIResponse,
  ExecutiveValueSummaryResponse,
  GridOutageResponse,
  HealthScore,
  MaintenanceRankingResponse,
  MaintenanceRecommendationsResponse,
  MembraneHealthResponse,
  PlantOverview,
  ResilienceCriticalityResponse,
  ResilienceGeneratorResponse,
  PumpCurve,
  RecommendationCard,
  TelemetryReading,
  WaterStream,
  WQAlertsResponse,
  WQContaminantMatrixResponse,
  WQForecastResponse,
  WQRemovalResponse,
  WQScalingResponse,
  WQStatusResponse,
} from './types';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = (body as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  getControlBoundary: () => request<ControlBoundary>('/control-boundary'),
  getOverview: () => request<PlantOverview>('/overview'),

  getAssets: () => request<Asset[]>('/assets'),
  getAsset: (assetId: string) => request<Asset>(`/assets/${assetId}`),
  getStreams: () => request<WaterStream[]>('/streams'),

  getHealthScores: () => request<HealthScore[]>('/health-scores'),
  getHealthScore: (assetId: string) => request<HealthScore>(`/health-scores/${assetId}`),

  getAnomalies: () => request<AnomalyResult[]>('/anomaly'),
  getAnomaly: (assetId: string) => request<AnomalyResult>(`/anomaly/${assetId}`),

  getTelemetry: (assetId: string) => request<TelemetryReading[]>(`/telemetry/${assetId}`),
  getPumpCurve: (assetId: string) => request<PumpCurve>(`/pump-curve/${assetId}`),

  getRecommendations: (assetId?: string) =>
    request<RecommendationCard[]>(
      assetId ? `/recommendations?asset_id=${encodeURIComponent(assetId)}` : '/recommendations',
    ),
  askS3M: (assetId: string) =>
    request<RecommendationCard>('/recommendations', {
      method: 'POST',
      body: JSON.stringify({ asset_id: assetId }),
    }),
  approveRecommendation: (recId: string, body: DecisionRequest = {}) =>
    request<RecommendationCard>(`/recommendations/${recId}/approve`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  rejectRecommendation: (recId: string, body: DecisionRequest = {}) =>
    request<RecommendationCard>(`/recommendations/${recId}/reject`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getAudit: (assetId?: string) =>
    request<AuditResponse>(
      assetId ? `/audit?asset_id=${encodeURIComponent(assetId)}` : '/audit',
    ),

  // Water Quality Intelligence (advisory, read-only)
  getWaterQualityStatus: () => request<WQStatusResponse>('/water-quality/status'),
  getWaterQualityContaminantMatrix: () =>
    request<WQContaminantMatrixResponse>('/water-quality/contaminant-matrix'),
  getWaterQualityRemoval: () => request<WQRemovalResponse>('/water-quality/removal'),
  getWaterQualityScaling: () => request<WQScalingResponse>('/water-quality/scaling'),
  getWaterQualityForecast: () => request<WQForecastResponse>('/water-quality/forecast'),
  getWaterQualityAlerts: () => request<WQAlertsResponse>('/water-quality/alerts'),

  // Equipment & Membrane Intelligence + Predictive Maintenance (advisory, preliminary)
  getEquipmentHealth: (assetId: string) =>
    request<EquipmentHealthResponse>(`/equipment/${encodeURIComponent(assetId)}/health`),
  getEquipmentRul: (assetId: string) =>
    request<EquipmentRulResponse>(`/equipment/${encodeURIComponent(assetId)}/rul`),
  getEquipmentFailureProbability: (assetId: string) =>
    request<EquipmentFailureProbabilityResponse>(
      `/equipment/${encodeURIComponent(assetId)}/failure-probability`,
    ),
  getEquipmentEnvelope: (assetId: string) =>
    request<EquipmentEnvelopeResponse>(`/equipment/${encodeURIComponent(assetId)}/envelope`),
  getEquipmentRootCause: (assetId: string) =>
    request<EquipmentRootCauseResponse>(`/equipment/${encodeURIComponent(assetId)}/root-cause`),
  getMembraneHealth: (assetId: string) =>
    request<MembraneHealthResponse>(`/membrane/${encodeURIComponent(assetId)}/health`),
  getMaintenanceRanking: () => request<MaintenanceRankingResponse>('/maintenance/ranking'),
  getMaintenanceRecommendations: () =>
    request<MaintenanceRecommendationsResponse>('/maintenance/recommendations'),

  // Energy Optimization (advisory, estimated)
  getEnergySummary: () => request<EnergySummaryResponse>('/energy/summary'),
  optimizeEnergy: () =>
    request<EnergyOptimizeResponse>('/energy/optimize', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  getEnergyLosses: () => request<EnergyLossesResponse>('/energy/losses'),

  // Resilience & Generator Command (advisory, preliminary)
  getResilienceCriticality: () =>
    request<ResilienceCriticalityResponse>('/resilience/criticality'),
  getResilienceGenerator: () => request<ResilienceGeneratorResponse>('/resilience/generator'),
  runGridOutage: () =>
    request<GridOutageResponse>('/resilience/grid-outage', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  // Executive Value / ROI (advisory, estimated — illustrative)
  getExecutiveValueSummary: () =>
    request<ExecutiveValueSummaryResponse>('/executive/value-summary'),
  getExecutiveRoi: () => request<ExecutiveROIResponse>('/executive/roi'),
};

export type ApiClient = typeof api;
