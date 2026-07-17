// react-query hooks for the WaterTwin API. Live views poll every 4 seconds.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import { api } from '../api/client';
import type { FacilitiesResponse, FleetOverview } from '../facilities/types';
import type {
  AnomalyResult,
  Asset,
  AssistantExamplesResponse,
  AuditResponse,
  ConfigActionRequest,
  ConfigDocument,
  ConfigDraftPayload,
  ConfigVersionsResponse,
  ComplianceLimitsResponse,
  ComplianceStatusResponse,
  CmmsAssetHistoryResponse,
  CmmsStatusResponse,
  CmmsWorkOrdersResponse,
  ControlBoundary,
  DecisionRequest,
  DocumentsResponse,
  EnergyLossesResponse,
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
  ModelsResponse,
  PlantOverview,
  PumpCurve,
  RecommendationCard,
  ResilienceCriticalityResponse,
  ResilienceGeneratorResponse,
  SecurityOverviewResponse,
  TelemetryReading,
  TrainingActionRequest,
  TrainingActionResponse,
  TrainingRecordResponse,
  TrainingRecordsResponse,
  TrainingScenariosResponse,
  TrainingSessionResponse,
  WaterStream,
  WQAlertsResponse,
  WQContaminantMatrixResponse,
  WQForecastResponse,
  WQRemovalResponse,
  WQScalingResponse,
  WQStatusResponse,
  WorkOrderDecisionRequest,
  WorkOrderResponse,
  WorkOrdersResponse,
} from '../api/types';

export const POLL_INTERVAL_MS = 4000;

export const queryKeys = {
  controlBoundary: ['control-boundary'] as const,
  overview: ['overview'] as const,
  facilities: ['facilities'] as const,
  fleetOverview: ['fleet-overview'] as const,
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
  equipmentHealth: (id: string) => ['equipment-health', id] as const,
  equipmentRul: (id: string) => ['equipment-rul', id] as const,
  equipmentFailureProbability: (id: string) => ['equipment-failure-probability', id] as const,
  equipmentEnvelope: (id: string) => ['equipment-envelope', id] as const,
  equipmentRootCause: (id: string) => ['equipment-root-cause', id] as const,
  membraneHealth: (id: string) => ['membrane-health', id] as const,
  maintenanceRanking: ['maintenance-ranking'] as const,
  maintenanceRecommendations: ['maintenance-recommendations'] as const,
  workOrders: ['work-orders'] as const,
  cmmsStatus: ['cmms-status'] as const,
  cmmsWorkOrders: ['cmms-work-orders'] as const,
  cmmsAssetHistory: (id: string) => ['cmms-asset-history', id] as const,
  energySummary: ['energy-summary'] as const,
  energyLosses: ['energy-losses'] as const,
  resilienceCriticality: ['resilience-criticality'] as const,
  resilienceGenerator: ['resilience-generator'] as const,
  executiveValueSummary: ['executive-value-summary'] as const,
  executiveRoi: ['executive-roi'] as const,
  assistantExamples: ['assistant-examples'] as const,
  documents: ['documents'] as const,
  config: ['config'] as const,
  configVersions: ['config-versions'] as const,
  models: ['models'] as const,
  complianceLimits: ['compliance-limits'] as const,
  complianceStatus: ['compliance-status'] as const,
  securityOverview: ['security-overview'] as const,
  trainingScenarios: ['training-scenarios'] as const,
  trainingRecords: ['training-records'] as const,
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

// --- Multi-facility administration hooks -----------------------------------

export function useFacilities(): UseQueryResult<FacilitiesResponse> {
  return useQuery({
    queryKey: queryKeys.facilities,
    queryFn: api.getFacilities,
    staleTime: POLL_INTERVAL_MS * 15,
  });
}

export function useFleetOverview(): UseQueryResult<FleetOverview> {
  return useQuery({
    queryKey: queryKeys.fleetOverview,
    queryFn: api.getFleetOverview,
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

// --- Equipment & Membrane Intelligence + Predictive Maintenance hooks ---

export function useEquipmentHealth(
  assetId: string | null,
): UseQueryResult<EquipmentHealthResponse> {
  return useQuery({
    queryKey: queryKeys.equipmentHealth(assetId ?? ''),
    queryFn: () => api.getEquipmentHealth(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useEquipmentRul(assetId: string | null): UseQueryResult<EquipmentRulResponse> {
  return useQuery({
    queryKey: queryKeys.equipmentRul(assetId ?? ''),
    queryFn: () => api.getEquipmentRul(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useEquipmentFailureProbability(
  assetId: string | null,
): UseQueryResult<EquipmentFailureProbabilityResponse> {
  return useQuery({
    queryKey: queryKeys.equipmentFailureProbability(assetId ?? ''),
    queryFn: () => api.getEquipmentFailureProbability(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useEquipmentEnvelope(
  assetId: string | null,
): UseQueryResult<EquipmentEnvelopeResponse> {
  return useQuery({
    queryKey: queryKeys.equipmentEnvelope(assetId ?? ''),
    queryFn: () => api.getEquipmentEnvelope(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useEquipmentRootCause(
  assetId: string | null,
): UseQueryResult<EquipmentRootCauseResponse> {
  return useQuery({
    queryKey: queryKeys.equipmentRootCause(assetId ?? ''),
    queryFn: () => api.getEquipmentRootCause(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useMembraneHealth(
  assetId: string | null,
): UseQueryResult<MembraneHealthResponse> {
  return useQuery({
    queryKey: queryKeys.membraneHealth(assetId ?? ''),
    queryFn: () => api.getMembraneHealth(assetId as string),
    enabled: !!assetId,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useMaintenanceRanking(): UseQueryResult<MaintenanceRankingResponse> {
  return useQuery({
    queryKey: queryKeys.maintenanceRanking,
    queryFn: api.getMaintenanceRanking,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useMaintenanceRecommendations(): UseQueryResult<MaintenanceRecommendationsResponse> {
  return useQuery({
    queryKey: queryKeys.maintenanceRecommendations,
    queryFn: api.getMaintenanceRecommendations,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

// --- Work orders / Maintenance Center (advisory, preliminary) ---

export function useWorkOrders(): UseQueryResult<WorkOrdersResponse> {
  return useQuery({
    queryKey: queryKeys.workOrders,
    queryFn: api.getWorkOrders,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useCmmsStatus(): UseQueryResult<CmmsStatusResponse> {
  return useQuery({
    queryKey: queryKeys.cmmsStatus,
    queryFn: api.getCmmsStatus,
    staleTime: POLL_INTERVAL_MS * 15,
  });
}

export function useCmmsWorkOrders(): UseQueryResult<CmmsWorkOrdersResponse> {
  return useQuery({
    queryKey: queryKeys.cmmsWorkOrders,
    queryFn: api.getCmmsWorkOrders,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useCmmsAssetHistory(
  assetId: string | null,
): UseQueryResult<CmmsAssetHistoryResponse> {
  return useQuery({
    queryKey: queryKeys.cmmsAssetHistory(assetId ?? ''),
    queryFn: () => api.getCmmsAssetHistory(assetId as string),
    enabled: !!assetId,
    staleTime: POLL_INTERVAL_MS * 15,
  });
}

export function useWorkOrderDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: WorkOrderDecisionRequest }): Promise<WorkOrderResponse> =>
      api.decideWorkOrder(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.workOrders });
      void qc.invalidateQueries({ queryKey: ['audit'] });
    },
  });
}

// --- Energy Optimization hooks (advisory, estimated) ---

export function useEnergySummary(): UseQueryResult<EnergySummaryResponse> {
  return useQuery({
    queryKey: queryKeys.energySummary,
    queryFn: api.getEnergySummary,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useEnergyLosses(): UseQueryResult<EnergyLossesResponse> {
  return useQuery({
    queryKey: queryKeys.energyLosses,
    queryFn: api.getEnergyLosses,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useOptimizeEnergy() {
  return useMutation({ mutationFn: () => api.optimizeEnergy() });
}

// --- Resilience & Generator Command hooks (advisory, preliminary) ---

export function useResilienceCriticality(): UseQueryResult<ResilienceCriticalityResponse> {
  return useQuery({
    queryKey: queryKeys.resilienceCriticality,
    queryFn: api.getResilienceCriticality,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useResilienceGenerator(): UseQueryResult<ResilienceGeneratorResponse> {
  return useQuery({
    queryKey: queryKeys.resilienceGenerator,
    queryFn: api.getResilienceGenerator,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useRunGridOutage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (): Promise<GridOutageResponse> => api.runGridOutage(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['recommendations'] });
      void qc.invalidateQueries({ queryKey: ['audit'] });
    },
  });
}

// --- Executive Value / ROI hooks (advisory, estimated — illustrative) ---

export function useExecutiveValueSummary(): UseQueryResult<ExecutiveValueSummaryResponse> {
  return useQuery({
    queryKey: queryKeys.executiveValueSummary,
    queryFn: api.getExecutiveValueSummary,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useExecutiveRoi(): UseQueryResult<ExecutiveROIResponse> {
  return useQuery({
    queryKey: queryKeys.executiveRoi,
    queryFn: api.getExecutiveRoi,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

// --- S3M Operations Assistant hooks (advisory, grounded) ---

export function useAssistantExamples(): UseQueryResult<AssistantExamplesResponse> {
  return useQuery({
    queryKey: queryKeys.assistantExamples,
    queryFn: api.getAssistantExamples,
    staleTime: POLL_INTERVAL_MS * 60,
  });
}

export function useDocuments(): UseQueryResult<DocumentsResponse> {
  return useQuery({
    queryKey: queryKeys.documents,
    queryFn: api.getDocuments,
    staleTime: POLL_INTERVAL_MS * 60,
  });
}

// --- Cyber-Physical Security hooks (advisory, read-only) ---

export function useSecurityOverview(): UseQueryResult<SecurityOverviewResponse> {
  return useQuery({
    queryKey: queryKeys.securityOverview,
    queryFn: api.getSecurityOverview,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useAskAssistant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ question, requestedBy }: { question: string; requestedBy?: string }) =>
      api.askAssistant(question, requestedBy),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['recommendations'] });
      void qc.invalidateQueries({ queryKey: ['audit'] });
    },
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

// --- Model governance registry (D1/D2) + compliance (A1 config store) ---

export function useModels(): UseQueryResult<ModelsResponse> {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: api.getModels,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useComplianceLimits(): UseQueryResult<ComplianceLimitsResponse> {
  return useQuery({
    queryKey: queryKeys.complianceLimits,
    queryFn: api.getComplianceLimits,
    staleTime: POLL_INTERVAL_MS * 15,
  });
}

export function useComplianceStatus(): UseQueryResult<ComplianceStatusResponse> {
  return useQuery({
    queryKey: queryKeys.complianceStatus,
    queryFn: api.getComplianceStatus,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useComplianceReport() {
  return useMutation({ mutationFn: () => api.getComplianceReport() });
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

// --- Administration / Configuration Workbench hooks ---

export function useConfig(): UseQueryResult<ConfigDocument> {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: api.getConfig,
    staleTime: POLL_INTERVAL_MS * 5,
  });
}

export function useConfigVersions(): UseQueryResult<ConfigVersionsResponse> {
  return useQuery({
    queryKey: queryKeys.configVersions,
    queryFn: api.getConfigVersions,
    staleTime: POLL_INTERVAL_MS * 5,
  });
}

function useInvalidateConfigViews() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.config });
    void qc.invalidateQueries({ queryKey: queryKeys.configVersions });
  };
}

export function useSaveConfigDraft() {
  const invalidate = useInvalidateConfigViews();
  return useMutation({
    mutationFn: (payload: ConfigDraftPayload) => api.saveConfigDraft(payload),
    onSuccess: invalidate,
  });
}

export function useSubmitConfig() {
  const invalidate = useInvalidateConfigViews();
  return useMutation({
    mutationFn: (body?: ConfigActionRequest) => api.submitConfig(body),
    onSuccess: invalidate,
  });
}

export function useApproveConfig() {
  const invalidate = useInvalidateConfigViews();
  return useMutation({
    mutationFn: (body?: ConfigActionRequest) => api.approveConfig(body),
    onSuccess: invalidate,
  });
}

export function useRejectConfig() {
  const invalidate = useInvalidateConfigViews();
  return useMutation({
    mutationFn: (body?: ConfigActionRequest) => api.rejectConfig(body),
    onSuccess: invalidate,
// --- Operator Training Simulator hooks (SIMULATION, sandboxed) ---

export function useTrainingScenarios(): UseQueryResult<TrainingScenariosResponse> {
  return useQuery({
    queryKey: queryKeys.trainingScenarios,
    queryFn: api.getTrainingScenarios,
    staleTime: POLL_INTERVAL_MS * 60,
  });
}

export function useTrainingRecords(): UseQueryResult<TrainingRecordsResponse> {
  return useQuery({
    queryKey: queryKeys.trainingRecords,
    queryFn: api.getTrainingRecords,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useStartTrainingSession() {
  return useMutation({
    mutationFn: ({ scenarioId, operator }: { scenarioId: string; operator?: string }): Promise<TrainingSessionResponse> =>
      api.startTrainingSession(scenarioId, operator),
  });
}

export function useCaptureTrainingAction() {
  return useMutation({
    mutationFn: ({
      sessionId,
      body,
    }: {
      sessionId: string;
      body: TrainingActionRequest;
    }): Promise<TrainingActionResponse> => api.captureTrainingAction(sessionId, body),
  });
}

export function useSubmitTrainingSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string): Promise<TrainingRecordResponse> =>
      api.submitTrainingSession(sessionId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.trainingRecords });
      void qc.invalidateQueries({ queryKey: ['audit'] });
    },
  });
}
