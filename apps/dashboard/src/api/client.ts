// Typed fetch wrappers for every /api/v1 endpoint consumed by the dashboard.

import type {
  AnomalyResult,
  Asset,
  AssistantExamplesResponse,
  AssistantResponse,
  AuditResponse,
  CmmsAssetHistoryResponse,
  CmmsStatusResponse,
  CmmsWorkOrdersResponse,
  ControlBoundary,
  DecisionRequest,
  DocumentsResponse,
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
  WorkOrderDecisionRequest,
  WorkOrderResponse,
  WorkOrdersResponse,
  WQAlertsResponse,
  WQContaminantMatrixResponse,
  WQForecastResponse,
  WQRemovalResponse,
  WQScalingResponse,
  WQStatusResponse,
} from './types';

import { getAccessToken } from '../auth/store';
import { refreshTokens } from '../auth/oidc';

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function doFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res = await doFetch(path, init);

  // On a 401 with a live session, try a single silent token refresh + retry.
  if (res.status === 401 && getAccessToken()) {
    const refreshed = await refreshTokens();
    if (refreshed) res = await doFetch(path, init);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = (body as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) {
      detail = detail || 'Not authenticated — please sign in.';
    } else if (res.status === 403) {
      detail = detail || 'Your role is not permitted to perform this action.';
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

  // Work orders / Maintenance Center (advisory; work orders derived from PdM alerts)
  getWorkOrders: () => request<WorkOrdersResponse>('/maintenance/work-orders'),
  getWorkOrder: (id: string) =>
    request<WorkOrderResponse>(`/maintenance/work-orders/${encodeURIComponent(id)}`),
  decideWorkOrder: (id: string, body: WorkOrderDecisionRequest) =>
    request<WorkOrderResponse>(
      `/maintenance/work-orders/${encodeURIComponent(id)}/decision`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  getCmmsStatus: () => request<CmmsStatusResponse>('/maintenance/cmms/status'),
  getCmmsWorkOrders: () => request<CmmsWorkOrdersResponse>('/maintenance/cmms/work-orders'),
  getCmmsAssetHistory: (assetId: string) =>
    request<CmmsAssetHistoryResponse>(
      `/maintenance/cmms/asset-history/${encodeURIComponent(assetId)}`,
    ),

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

  // S3M Operations Assistant (advisory, grounded)
  askAssistant: (question: string, requestedBy?: string) =>
    request<AssistantResponse>('/assistant/ask', {
      method: 'POST',
      body: JSON.stringify({ question, requested_by: requestedBy ?? null }),
    }),
  getAssistantExamples: () => request<AssistantExamplesResponse>('/assistant/examples'),
  getDocuments: () => request<DocumentsResponse>('/documents'),
};

export type ApiClient = typeof api;
