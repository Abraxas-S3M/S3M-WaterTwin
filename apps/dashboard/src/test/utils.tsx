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
    if (path.startsWith('/water-quality/status')) return json(overrides.wqStatus ?? fx.wqStatus);
    if (path.startsWith('/water-quality/contaminant-matrix'))
      return json(overrides.wqContaminantMatrix ?? fx.wqContaminantMatrix);
    if (path.startsWith('/water-quality/removal')) return json(overrides.wqRemoval ?? fx.wqRemoval);
    if (path.startsWith('/water-quality/scaling')) return json(overrides.wqScaling ?? fx.wqScaling);
    if (path.startsWith('/water-quality/forecast')) return json(overrides.wqForecast ?? fx.wqForecast);
    if (path.startsWith('/water-quality/alerts')) return json(overrides.wqAlerts ?? fx.wqAlerts);
    if (path.startsWith('/overview')) return json(overrides.overview ?? fx.overview);
    if (path.startsWith('/maintenance/ranking'))
      return json(overrides.maintenanceRanking ?? fx.maintenanceRanking);
    if (path.startsWith('/maintenance/recommendations'))
      return json(overrides.maintenanceRecommendations ?? fx.maintenanceRecommendations);
    if (/\/equipment\/.+\/health/.test(path))
      return json(overrides.equipmentHealth ?? fx.equipmentHealth);
    if (/\/equipment\/.+\/rul/.test(path)) return json(overrides.equipmentRul ?? fx.equipmentRul);
    if (/\/equipment\/.+\/failure-probability/.test(path))
      return json(overrides.equipmentFailureProbability ?? fx.equipmentFailureProbability);
    if (/\/equipment\/.+\/envelope/.test(path))
      return json(overrides.equipmentEnvelope ?? fx.equipmentEnvelope);
    if (/\/equipment\/.+\/root-cause/.test(path))
      return json(overrides.equipmentRootCause ?? fx.equipmentRootCause);
    if (/\/membrane\/.+\/health/.test(path))
      return json(overrides.membraneHealth ?? fx.membraneHealth);

    // Value layer: Energy / Resilience / Executive.
    if (path.startsWith('/energy/summary')) return json(overrides.energySummary ?? fx.energySummary);
    if (path.startsWith('/energy/optimize'))
      return json(overrides.energyOptimize ?? fx.energyOptimize);
    if (path.startsWith('/energy/losses')) return json(overrides.energyLosses ?? fx.energyLosses);
    if (path.startsWith('/resilience/criticality'))
      return json(overrides.resilienceCriticality ?? fx.resilienceCriticality);
    if (path.startsWith('/resilience/generator'))
      return json(overrides.resilienceGenerator ?? fx.resilienceGenerator);
    if (path.startsWith('/resilience/grid-outage'))
      return json(overrides.gridOutage ?? fx.gridOutage);
    if (path.startsWith('/executive/value-summary'))
      return json(overrides.executiveValueSummary ?? fx.executiveValueSummary);
    if (path.startsWith('/executive/roi')) return json(overrides.executiveRoi ?? fx.executiveRoi);
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
