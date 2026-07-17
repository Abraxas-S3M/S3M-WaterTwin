import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResilienceCommand } from './ResilienceCommand';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('ResilienceCommand', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders generator status and criticality ranking on load', async () => {
    mock = installFetchMock();
    renderWithProviders(<ResilienceCommand />);

    await waitFor(() => expect(screen.getByTestId('resilience-command')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('generator-status')).toBeInTheDocument());
    expect(screen.getByTestId('criticality-ranking')).toBeInTheDocument();

    // Preliminary provenance is visible.
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'preliminary')).toBe(true);
  });

  it('runs the grid-outage scenario and renders a shed plan keeping the HP pump last', async () => {
    mock = installFetchMock();
    renderWithProviders(<ResilienceCommand />);

    await waitFor(() => expect(screen.getByTestId('run-grid-outage')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('run-grid-outage'));

    await waitFor(() => expect(screen.getByTestId('load-shed-plan')).toBeInTheDocument());

    // The POST fired.
    const call = mock.calls.find(
      (c) => c.method === 'POST' && /\/resilience\/grid-outage$/.test(c.url),
    );
    expect(call).toBeTruthy();

    // The HP-pump load is retained (shed last) and the recommendation is approvable.
    const hpRow = screen.getByTestId('shed-row-AST-HPP-01');
    expect(hpRow).toHaveTextContent('retained');
    expect(screen.getByTestId('resilience-recommendation')).toBeInTheDocument();
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <ResilienceCommand />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('resilience-command')).toBeInTheDocument());
  });
});
