import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// echarts renders to a canvas that jsdom does not implement; mock the chart so
// the full app shell (which imports the pump-curve chart) can render.
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}));

import App from './App';
import { installFetchMock, renderWithProviders } from './test/utils';
import { useDashboardStore } from './state/store';

describe('App shell', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ page: 'command', selectedAssetId: null });
  });

  it('keeps the safety boundary banner visible and navigates to Predictive Maintenance', async () => {
    mock = installFetchMock();
    renderWithProviders(<App />);

    // Boundary banner is always present.
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/does not write to plant controls/i)).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole('button', { name: /Predictive Maintenance/i }));
    await waitFor(() =>
      expect(screen.getByTestId('predictive-maintenance')).toBeInTheDocument(),
    );

    // Banner remains visible on the new page.
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
  });
});
