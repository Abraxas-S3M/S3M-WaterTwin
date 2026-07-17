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
    useDashboardStore.setState({
      page: 'command',
      selectedAssetId: null,
      displayMode: 'standard',
      reportView: null,
    });
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

  it('does not regress the desktop layout (nav + shell render by default)', async () => {
    mock = installFetchMock();
    renderWithProviders(<App />);

    expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('command-overview')).toBeInTheDocument());
    // Control room / report overlays are not shown in the default desktop mode.
    expect(screen.queryByTestId('control-room')).not.toBeInTheDocument();
    expect(screen.queryByTestId('shift-report')).not.toBeInTheDocument();
  });

  it('enters the control-room display mode with minimal chrome', async () => {
    mock = installFetchMock();
    renderWithProviders(<App />);

    await userEvent.click(screen.getByTestId('enter-control-room'));
    await waitFor(() => expect(screen.getByTestId('control-room')).toBeInTheDocument());

    // Minimal chrome: the primary nav and safety banner are replaced.
    expect(screen.queryByRole('navigation', { name: /primary/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId('safety-boundary-banner')).not.toBeInTheDocument();
  });

  it('opens the shift and executive report overlays from the nav', async () => {
    mock = installFetchMock();
    renderWithProviders(<App />);

    await userEvent.click(screen.getByTestId('open-shift-report'));
    await waitFor(() => expect(screen.getByTestId('shift-report')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('report-close'));
    await waitFor(() => expect(screen.queryByTestId('shift-report')).not.toBeInTheDocument());

    await userEvent.click(screen.getByTestId('open-executive-report'));
    await waitFor(() => expect(screen.getByTestId('executive-report')).toBeInTheDocument());
  });
});
