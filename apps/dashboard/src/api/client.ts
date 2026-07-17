// Typed fetch wrappers for every /api/v1 endpoint consumed by the dashboard.

import type {
  AnomalyResult,
  Asset,
  AuditResponse,
  ControlBoundary,
  DecisionRequest,
  HealthScore,
  PlantOverview,
  PumpCurve,
  RecommendationCard,
  TelemetryReading,
  WaterStream,
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
};

export type ApiClient = typeof api;
