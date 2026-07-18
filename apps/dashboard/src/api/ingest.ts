// Typed client + react-query hooks for the optional watertwin-ingest service.
//
// The Data Intake page talks to this service, which turns an uploaded file into
// a draft change through watertwin-api's EXISTING configuration lifecycle. The
// service is read-only to OT: it never writes to SCADA/PLC/OPC UA/MQTT and never
// issues a control command. When the service is unavailable the status query
// resolves to `available: false` and the UI degrades gracefully.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query';

import { getAccessToken } from '../auth/store';
import type {
  IngestClassification,
  IngestClassifyRequest,
  IngestHistoryResponse,
  IngestOnboardingResponse,
  IngestPreview,
  IngestStatusResponse,
  IngestSubmitRequest,
  IngestSubmitResult,
} from './types';

export const INGEST_BASE: string =
  (import.meta.env.VITE_INGEST_BASE as string | undefined) ?? '/api/v1/ingest';

export class IngestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'IngestError';
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${INGEST_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.clone().json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new IngestError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const ingestApi = {
  getStatus: (): Promise<IngestStatusResponse> => request<IngestStatusResponse>('/status'),
  getOnboarding: (): Promise<IngestOnboardingResponse> =>
    request<IngestOnboardingResponse>('/onboarding'),
  classify: (body: IngestClassifyRequest): Promise<IngestClassification> =>
    request<IngestClassification>('/classify', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getPreview: (uploadId: string): Promise<IngestPreview> =>
    request<IngestPreview>(`/uploads/${encodeURIComponent(uploadId)}/preview`),
  submit: (body: IngestSubmitRequest): Promise<IngestSubmitResult> =>
    request<IngestSubmitResult>('/submit', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getHistory: (): Promise<IngestHistoryResponse> => request<IngestHistoryResponse>('/history'),
  // Original-file download is admin-only and enforced server-side. Returned as a
  // URL for an anchor download so the browser handles the binary transfer.
  originalDownloadUrl: (uploadId: string): string =>
    `${INGEST_BASE}/uploads/${encodeURIComponent(uploadId)}/original`,
};

export type IngestClient = typeof ingestApi;

const keys = {
  status: ['ingest', 'status'] as const,
  onboarding: ['ingest', 'onboarding'] as const,
  history: ['ingest', 'history'] as const,
  preview: (id: string) => ['ingest', 'preview', id] as const,
};

export function useIngestStatus(): UseQueryResult<IngestStatusResponse> {
  return useQuery({
    queryKey: keys.status,
    queryFn: ingestApi.getStatus,
    // Availability rarely flips; a hard failure simply reads as unavailable.
    staleTime: 60_000,
    retry: false,
  });
}

export function useIngestOnboarding(
  enabled = true,
): UseQueryResult<IngestOnboardingResponse> {
  return useQuery({
    queryKey: keys.onboarding,
    queryFn: ingestApi.getOnboarding,
    enabled,
    retry: false,
  });
}

export function useIngestHistory(enabled = true): UseQueryResult<IngestHistoryResponse> {
  return useQuery({
    queryKey: keys.history,
    queryFn: ingestApi.getHistory,
    enabled,
    retry: false,
  });
}

export function useIngestPreview(
  uploadId: string | null,
): UseQueryResult<IngestPreview> {
  return useQuery({
    queryKey: keys.preview(uploadId ?? 'none'),
    queryFn: () => ingestApi.getPreview(uploadId as string),
    enabled: Boolean(uploadId),
    // The preview is produced asynchronously; poll until it is ready.
    refetchInterval: (query) =>
      query.state.data && query.state.data.status === 'pending' ? 1500 : false,
    retry: false,
  });
}

export function useClassifyUpload(): UseMutationResult<
  IngestClassification,
  Error,
  IngestClassifyRequest
> {
  return useMutation({ mutationFn: (body: IngestClassifyRequest) => ingestApi.classify(body) });
}

export function useSubmitIngest(): UseMutationResult<
  IngestSubmitResult,
  Error,
  IngestSubmitRequest
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: IngestSubmitRequest) => ingestApi.submit(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.history });
      void qc.invalidateQueries({ queryKey: keys.onboarding });
    },
  });
}
