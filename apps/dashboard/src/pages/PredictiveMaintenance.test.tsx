import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PredictiveMaintenance } from './PredictiveMaintenance';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useDashboardStore } from '../state/store';

describe('PredictiveMaintenance', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ selectedAssetId: null, page: 'command' });
  });

  it('renders the risk-ranked table from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<PredictiveMaintenance />);

    await waitFor(() =>
      expect(screen.getByTestId('predictive-maintenance')).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByTestId('pdm-ranking-table')).toBeInTheDocument());

    expect(screen.getByText('High-Pressure Pump A')).toBeInTheDocument();
    expect(screen.getByText('RO Membrane Array (Train 1)')).toBeInTheDocument();

    // Forecasts are flagged PRELIMINARY.
    expect(screen.getAllByTestId('provenance-badge').length).toBeGreaterThan(0);
  });

  it('opens the detail panel on row click and round-trips an approve', async () => {
    mock = installFetchMock();
    renderWithProviders(<PredictiveMaintenance />);

    await waitFor(() => expect(screen.getByTestId('pdm-row-AST-HPP-01')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('pdm-row-AST-HPP-01'));

    await waitFor(() => expect(screen.getByTestId('pdm-detail')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('approve-button')).toBeInTheDocument());

    await userEvent.click(screen.getByTestId('approve-button'));
    await waitFor(() => {
      const call = mock.calls.find(
        (c) => c.method === 'POST' && /\/recommendations\/.+\/approve$/.test(c.url),
      );
      expect(call).toBeTruthy();
    });
  });
});
