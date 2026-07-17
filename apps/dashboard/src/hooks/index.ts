// react-query hooks for the WaterTwin API. Live views poll every 4 seconds.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import { api } from '../api/client';
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
  WQAlertsResponse,
  WQContaminantMatrixResponse,
  WQForecastResponse,
  WQRemovalResponse,
  WQScalingResponse,
  WQStatusResponse,
} from '../api/types';

export const POLL_INTERVAL_MS = 4000;

export const queryKeys = {
  controlBoundary: ['control-boundary'] as const,
  overview: ['overview'] as const,
  assets: ['assets'] as const,
  asset: (id: string) => ['asset', id] as const,
  streams: ['streams'] as const,
  healthScores: ['health-scores'] as const,
  health: (id: string) => ['health', id] as const,
  anomalies: ['anomalies'] as const,
  anomaly: (id: string) => ['anomaly', id] as const,
  telemetry: (id: string) => ['telemetry', id] as const,
  pumpCurve: (id: string) => ['pump-curve', id] as const,
  recommendations: (id?: string) => ['recommendations', id ?? 'all'] as const,
  audit: (id?: string) => ['audit', id ?? 'all'] as const,
  wqStatus: ['wq-status'] as const,
  wqContaminantMatrix: ['wq-contaminant-matrix'] as const,
  wqRemoval: ['wq-removal'] as const,
  wqScaling: ['wq-scaling'] as const,
  wqForecast: ['wq-forecast'] as const,
  wqAlerts: ['wq-alerts'] as const,
};

// Control boundary rarely changes; poll slowly but keep it fresh.
export function useControlBoundary(): UseQueryResult<ControlBoundary> {
  return useQuery({
    queryKey: queryKeys.controlBoundary,
    queryFn: api.getControlBoundary,
    refetchInterval: POLL_INTERVAL_MS * 15,
    staleTime: POLL_INTERVAL_MS * 5,
  });
}

export function useOverview(): UseQueryResult<PlantOverview> {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: api.getOverview,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useAssets(): UseQueryResult<Asset[]> {
  return useQuery({
    queryKey: queryKeys.assets,
    queryFn: api.getAssets,
    staleTime: POLL_INTERVAL_MS * 30,
  });
}

export function useAsset(assetId: string | null): UseQueryResult<Asset> {
  return useQuery({
    queryKey: queryKeys.asset(assetId ?? ''),
    queryFn: () => api.getAsset(assetId as string),
    enabled: !!assetId,
    staleTime: POLL_INTERVAL_MS * 30,
  });
}

export function useStreams(): UseQueryResult<WaterStream[]> {
  return useQuery({
    queryKey: queryKeys.streams,
    queryFn: api.getStreams,
    staleTime: POLL_INTERVAL_MS * 60,
  });
}

export function useHealthScores(): UseQueryResult<HealthScore[]> {
  return useQuery({
    queryKey: queryKeys.healthScores,
    queryFn: api.getHealthScores,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useHealth(assetId: string | null): UseQueryResult<HealthScore> {
  return useQuery({
    queryKey: queryKeys.health(assetId ?? ''),
    queryFn: () => api.getHealthScore(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useAnomaly(assetId: string | null): UseQueryResult<AnomalyResult> {
  return useQuery({
    queryKey: queryKeys.anomaly(assetId ?? ''),
    queryFn: () => api.getAnomaly(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useTelemetry(assetId: string | null): UseQueryResult<TelemetryReading[]> {
  return useQuery({
    queryKey: queryKeys.telemetry(assetId ?? ''),
    queryFn: () => api.getTelemetry(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function usePumpCurve(assetId: string | null): UseQueryResult<PumpCurve> {
  return useQuery({
    queryKey: queryKeys.pumpCurve(assetId ?? ''),
    queryFn: () => api.getPumpCurve(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useRecommendations(assetId?: string): UseQueryResult<RecommendationCard[]> {
  return useQuery({
    queryKey: queryKeys.recommendations(assetId),
    queryFn: () => api.getRecommendations(assetId),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useAudit(assetId?: string): UseQueryResult<AuditResponse> {
  return useQuery({
    queryKey: queryKeys.audit(assetId),
    queryFn: () => api.getAudit(assetId),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

// --- Water Quality Intelligence hooks (advisory, preliminary) ---

export function useWaterQualityStatus(): UseQueryResult<WQStatusResponse> {
  return useQuery({
    queryKey: queryKeys.wqStatus,
    queryFn: api.getWaterQualityStatus,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useWaterQualityContaminantMatrix(): UseQueryResult<WQContaminantMatrixResponse> {
  return useQuery({
    queryKey: queryKeys.wqContaminantMatrix,
    queryFn: api.getWaterQualityContaminantMatrix,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useWaterQualityRemoval(): UseQueryResult<WQRemovalResponse> {
  return useQuery({
    queryKey: queryKeys.wqRemoval,
    queryFn: api.getWaterQualityRemoval,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useWaterQualityScaling(): UseQueryResult<WQScalingResponse> {
  return useQuery({
    queryKey: queryKeys.wqScaling,
    queryFn: api.getWaterQualityScaling,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useWaterQualityForecast(): UseQueryResult<WQForecastResponse> {
  return useQuery({
    queryKey: queryKeys.wqForecast,
    queryFn: api.getWaterQualityForecast,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useWaterQualityAlerts(): UseQueryResult<WQAlertsResponse> {
  return useQuery({
    queryKey: queryKeys.wqAlerts,
    queryFn: api.getWaterQualityAlerts,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

function useInvalidateRecommendationViews() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ['recommendations'] });
    void qc.invalidateQueries({ queryKey: ['audit'] });
    void qc.invalidateQueries({ queryKey: queryKeys.overview });
  };
}

export function useAskS3M() {
  const invalidate = useInvalidateRecommendationViews();
  return useMutation({
    mutationFn: (assetId: string) => api.askS3M(assetId),
    onSuccess: invalidate,
  });
}

export function useDecision() {
  const invalidate = useInvalidateRecommendationViews();
  return useMutation({
    mutationFn: ({
      recId,
      decision,
      body,
    }: {
      recId: string;
      decision: 'approve' | 'reject';
      body?: DecisionRequest;
    }) =>
      decision === 'approve'
        ? api.approveRecommendation(recId, body)
        : api.rejectRecommendation(recId, body),
    onSuccess: invalidate,
  });
}
