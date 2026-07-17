import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WaterQuality } from './WaterQuality';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('WaterQuality', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders every WQ panel from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<WaterQuality />);

    await waitFor(() => expect(screen.getByTestId('water-quality')).toBeInTheDocument());

    // All five panels present.
    expect(screen.getByTestId('wq-status')).toBeInTheDocument();
    expect(screen.getByTestId('wq-contaminant-matrix')).toBeInTheDocument();
    expect(screen.getByTestId('wq-removal')).toBeInTheDocument();
    expect(screen.getByTestId('wq-scaling')).toBeInTheDocument();
    expect(screen.getByTestId('wq-forecast')).toBeInTheDocument();
    expect(screen.getByTestId('wq-alerts')).toBeInTheDocument();

    // Data from fixtures surfaced.
    expect(screen.getByRole('heading', { name: /Water Quality Intelligence/i })).toBeInTheDocument();
    expect(screen.getAllByText('Boron').length).toBeGreaterThan(0);
    expect(screen.getByText('BaSO4')).toBeInTheDocument();

    // Preliminary provenance is visible (nothing presented as validated).
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.length).toBeGreaterThan(0);
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'preliminary')).toBe(true);

    // An alert surfaced as an approvable recommendation.
    await waitFor(() => expect(screen.getByTestId('recommendation-card')).toBeInTheDocument());
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <WaterQuality />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('water-quality')).toBeInTheDocument());
  });

  it('round-trips an approve action for a WQ alert to the API', async () => {
    mock = installFetchMock();
    renderWithProviders(<WaterQuality />);

    await waitFor(() => expect(screen.getByTestId('approve-button')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('approve-button'));

    await waitFor(() => {
      const approveCall = mock.calls.find(
        (c) => c.method === 'POST' && /\/recommendations\/.+\/approve$/.test(c.url),
      );
      expect(approveCall).toBeTruthy();
    });
  });
});
