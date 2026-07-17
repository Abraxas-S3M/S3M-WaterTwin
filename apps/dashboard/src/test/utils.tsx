import type { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { vi } from 'vitest';
import * as fx from './fixtures';

export function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(ui: ReactElement, client = makeClient()) {
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

export interface FetchMock {
  calls: { url: string; method: string; body?: unknown }[];
  restore: () => void;
}

/**
 * Installs a fetch mock that maps the /api/v1 surface to fixtures. Mutating
 * POSTs (approve/reject/ask) are recorded and return an updated payload so
 * approve/reject round-trips can be asserted end-to-end.
 */
export function installFetchMock(overrides: Record<string, unknown> = {}): FetchMock {
  const calls: FetchMock['calls'] = [];

  const json = (data: unknown, status = 200) =>
    Promise.resolve(
      new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

  const handler = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ url, method, body });

    const path = url.replace(/^.*\/api\/v1/, '');

    if (path.startsWith('/control-boundary')) return json(fx.controlBoundary);
    if (path.startsWith('/overview')) return json(overrides.overview ?? fx.overview);
    if (path.startsWith('/assets/')) return json(fx.hpAsset);
    if (path.startsWith('/assets')) return json(fx.assets);
    if (path.startsWith('/streams')) return json([]);
    if (path.startsWith('/health-scores/')) return json(fx.hpHealth);
    if (path.startsWith('/health-scores')) return json([fx.hpHealth]);
    if (path.startsWith('/anomaly/')) return json(fx.hpAnomaly);
    if (path.startsWith('/anomaly')) return json([fx.hpAnomaly]);
    if (path.startsWith('/telemetry/')) return json(fx.hpTelemetry);
    if (path.startsWith('/pump-curve/')) return json(fx.hpPumpCurve);
    if (path.startsWith('/audit')) return json(fx.audit);

    if (path.startsWith('/recommendations') && method === 'POST') {
      if (/\/approve$/.test(path)) return json({ ...fx.recommendation, approval_status: 'approved' });
      if (/\/reject$/.test(path)) return json({ ...fx.recommendation, approval_status: 'rejected' });
      return json(fx.recommendation, 201);
    }
    if (path.startsWith('/recommendations')) return json([fx.recommendation]);

    return json({ detail: `unhandled ${path}` }, 404);
  };

  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(handler as typeof fetch);

  return {
    calls,
    restore: () => spy.mockRestore(),
  };
}
