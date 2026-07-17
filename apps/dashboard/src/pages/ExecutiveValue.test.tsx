import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { ExecutiveValue } from './ExecutiveValue';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('ExecutiveValue', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('shows the disclaimer banner and ESTIMATED badges', async () => {
    mock = installFetchMock();
    renderWithProviders(<ExecutiveValue />);

    await waitFor(() => expect(screen.getByTestId('executive-value')).toBeInTheDocument());

    // Mandatory, visible disclaimer.
    const disclaimer = screen.getByTestId('executive-disclaimer');
    expect(disclaimer).toBeInTheDocument();
    expect(disclaimer).toHaveTextContent(/not validated savings/i);

    // Every ROI/benefit figure is flagged ESTIMATED (nothing validated/guaranteed).
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.length).toBeGreaterThan(0);
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'estimated')).toBe(true);
    expect(badges.every((b) => b.getAttribute('data-provenance') !== 'measured')).toBe(true);
  });

  it('renders ROI, annualized benefit, payback and all benefit categories', async () => {
    mock = installFetchMock();
    renderWithProviders(<ExecutiveValue />);

    await waitFor(() => expect(screen.getByTestId('value-components')).toBeInTheDocument());

    expect(screen.getByText('Pilot ROI')).toBeInTheDocument();
    expect(screen.getByText('Annualized Benefit')).toBeInTheDocument();
    expect(screen.getByText('Payback Period')).toBeInTheDocument();

    for (const label of [
      'Downtime avoided',
      'Energy savings',
      'Chemical savings',
      'Water-loss avoided',
      'Maintenance savings',
      'Capex deferred',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText('Total annualized benefit')).toBeInTheDocument();
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <ExecutiveValue />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('executive-value')).toBeInTheDocument());
  });
});
