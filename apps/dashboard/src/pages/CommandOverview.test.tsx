import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CommandOverview } from './CommandOverview';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('CommandOverview', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders KPIs from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<CommandOverview />);

    await waitFor(() => expect(screen.getByTestId('command-overview')).toBeInTheDocument());

    expect(screen.getByText('Plant Health')).toBeInTheDocument();
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('Recovery')).toBeInTheDocument();
    expect(screen.getByText('Permeate Conductivity')).toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.getByText('Service-Continuity Risk')).toBeInTheDocument();

    // Plant health value from fixture.
    expect(screen.getByText('79.5')).toBeInTheDocument();
    // Active recommendation surfaced.
    expect(screen.getByTestId('recommendation-card')).toBeInTheDocument();
    // Provenance badges present (nothing presented as validated/measured).
    expect(screen.getAllByTestId('provenance-badge').length).toBeGreaterThan(0);
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <CommandOverview />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('command-overview')).toBeInTheDocument());
  });

  it('round-trips an approve action to the API', async () => {
    mock = installFetchMock();
    renderWithProviders(<CommandOverview />);

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
