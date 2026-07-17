import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EnergyOptimization } from './EnergyOptimization';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('EnergyOptimization', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders the optimal setpoint and estimated savings', async () => {
    mock = installFetchMock();
    renderWithProviders(<EnergyOptimization />);

    await waitFor(() => expect(screen.getByTestId('energy-optimization')).toBeInTheDocument());

    // Optimal setpoint is rendered (pressure + SEC from the fixture).
    expect(screen.getByTestId('energy-setpoint')).toBeInTheDocument();
    expect(screen.getByText('Optimal (estimated)')).toBeInTheDocument();
    expect(screen.getAllByText(/57(\.0)? bar/).length).toBeGreaterThan(0);

    // Estimated provenance is visible (nothing presented as validated).
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'estimated')).toBe(true);

    // Energy-by-asset + avoidable-loss panels present.
    expect(screen.getByTestId('energy-by-asset')).toBeInTheDocument();
    expect(screen.getByTestId('energy-losses')).toBeInTheDocument();
  });

  it('runs the optimizer and shows the optimized result', async () => {
    mock = installFetchMock();
    renderWithProviders(<EnergyOptimization />);

    await waitFor(() => expect(screen.getByTestId('run-optimize')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('run-optimize'));

    await waitFor(() => expect(screen.getByTestId('optimize-result')).toBeInTheDocument());
    const optimizeCall = mock.calls.find(
      (c) => c.method === 'POST' && /\/energy\/optimize$/.test(c.url),
    );
    expect(optimizeCall).toBeTruthy();
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <EnergyOptimization />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('energy-optimization')).toBeInTheDocument());
  });
});
