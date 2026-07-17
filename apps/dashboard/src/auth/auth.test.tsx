import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { screen } from '@testing-library/react';

// Force OIDC to be "configured" so the login gate and sign-out control render.
vi.mock('./config', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./config')>();
  return { ...actual, isAuthConfigured: () => true };
});

// echarts renders to a canvas jsdom does not implement; mock it so importing the
// full App (which pulls in the pump-curve chart) is safe.
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}));

import App from '../App';
import { RecommendationCard } from '../components/RecommendationCard';
import { ScenarioControls } from '../components/ScenarioControls';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { recommendation } from '../test/fixtures';
import { useAuthStore } from './store';

function setRoles(roles: string[]) {
  useAuthStore.setState({
    status: 'authenticated',
    username: 'test-user',
    roles,
    accessToken: 't',
    refreshToken: null,
    expiresAt: null,
    error: null,
  });
}

describe('auth: login gate', () => {
  let mock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    // Anonymous session -> the gate should render.
    useAuthStore.getState().clearSession();
    mock = installFetchMock();
  });

  afterEach(() => {
    mock?.restore();
  });

  it('renders the login gate (not the console) when unauthenticated', async () => {
    renderWithProviders(<App />);
    // The redirect-callback check resolves on a microtask, then the gate shows.
    expect(await screen.findByTestId('login-gate')).toBeInTheDocument();
    expect(screen.getByTestId('login-button')).toBeInTheDocument();
    // The advisory/read-only banner stays visible on the login screen.
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    // The console navigation is NOT rendered while gated.
    expect(screen.queryByRole('button', { name: /Command Overview/i })).not.toBeInTheDocument();
  });
});

describe('auth: role gating', () => {
  afterEach(() => {
    // Restore a full-privilege session for other suites.
    setRoles(['viewer', 'operator', 'engineer', 'admin', 'auditor']);
  });

  it('hides approve/reject for a viewer', () => {
    setRoles(['viewer']);
    renderWithProviders(
      <RecommendationCard rec={recommendation} onApprove={() => {}} onReject={() => {}} />,
    );
    expect(screen.queryByTestId('approve-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('reject-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('approve-role-gate')).toBeInTheDocument();
  });

  it('shows approve/reject for an operator', () => {
    setRoles(['operator']);
    renderWithProviders(
      <RecommendationCard rec={recommendation} onApprove={() => {}} onReject={() => {}} />,
    );
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    expect(screen.getByTestId('reject-button')).toBeInTheDocument();
    expect(screen.queryByTestId('approve-role-gate')).not.toBeInTheDocument();
  });

  it('disables non-baseline scenario controls for a viewer', () => {
    setRoles(['viewer']);
    renderWithProviders(<ScenarioControls />);
    expect(screen.getByTestId('scenario-role-gate')).toBeInTheDocument();
    expect(screen.getByTestId('scenario-peak_demand')).toBeDisabled();
    // Baseline stays selectable for everyone.
    expect(screen.getByTestId('scenario-baseline')).not.toBeDisabled();
  });

  it('enables scenario controls for an engineer', () => {
    setRoles(['engineer']);
    renderWithProviders(<ScenarioControls />);
    expect(screen.queryByTestId('scenario-role-gate')).not.toBeInTheDocument();
    expect(screen.getByTestId('scenario-peak_demand')).not.toBeDisabled();
  });
});
