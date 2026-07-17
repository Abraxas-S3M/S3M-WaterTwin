import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// echarts renders to a canvas that jsdom does not implement; mock the chart.
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}));

import { AssetTwin } from './AssetTwin';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useDashboardStore } from '../state/store';

describe('AssetTwin', () => {
  let mock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    useDashboardStore.setState({ selectedAssetId: 'AST-HPP-01', operatorName: 'tester' });
  });
  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ selectedAssetId: null });
  });

  it('renders identity, health, contribution breakdown, anomaly and telemetry from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<AssetTwin />);

    await waitFor(() => expect(screen.getByTestId('asset-twin')).toBeInTheDocument());

    // Identity
    expect(screen.getByRole('heading', { name: /High-Pressure Pump A/i })).toBeInTheDocument();
    expect(screen.getByText('KSB')).toBeInTheDocument();

    // Health + contribution breakdown (top health card is the first of each;
    // the deepened page also renders a component-health card lower down).
    await waitFor(() => expect(screen.getAllByTestId('health-bar').length).toBeGreaterThan(0));
    expect(screen.getAllByTestId('contribution-breakdown').length).toBeGreaterThan(0);
    expect(screen.getByText('Vibration trend')).toBeInTheDocument();

    // Anomaly domains
    await waitFor(() => expect(screen.getByText('Mechanical')).toBeInTheDocument());

    // Live telemetry
    await waitFor(() => expect(screen.getByText('Flow M3h')).toBeInTheDocument());

    // Recommendation present with approve/reject controls
    await waitFor(() => expect(screen.getByTestId('recommendation-card')).toBeInTheDocument());
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
  });

  it('shows preliminary RUL with a PRELIMINARY badge and component health + root-cause', async () => {
    mock = installFetchMock();
    renderWithProviders(<AssetTwin />);

    await waitFor(() => expect(screen.getByTestId('rul-panel')).toBeInTheDocument());
    const rulPanel = screen.getByTestId('rul-panel');
    expect(within(rulPanel).getByText('Remaining Useful Life')).toBeInTheDocument();
    // RUL is explicitly labelled as preliminary (not validated).
    const badges = within(rulPanel).getAllByTestId('provenance-badge');
    expect(badges.length).toBeGreaterThan(0);
    expect(badges[0]).toHaveAttribute('data-provenance', 'preliminary');

    // Deepened panels are present.
    await waitFor(() => expect(screen.getByTestId('component-health')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('failure-probability-panel')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('operating-envelope')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('root-cause')).toBeInTheDocument());
    expect(screen.getByText('Membrane fouling')).toBeInTheDocument();
  });

  it('asks S3M and round-trips a reject to the API, reflected in audit', async () => {
    mock = installFetchMock();
    renderWithProviders(<AssetTwin />);

    await waitFor(() => expect(screen.getByTestId('ask-s3m-button')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('ask-s3m-button'));

    await waitFor(() => {
      const askCall = mock.calls.find(
        (c) => c.method === 'POST' && /\/recommendations$/.test(c.url),
      );
      expect(askCall).toBeTruthy();
    });

    await userEvent.click(screen.getByTestId('reject-button'));
    await waitFor(() => {
      const rejectCall = mock.calls.find(
        (c) => c.method === 'POST' && /\/recommendations\/.+\/reject$/.test(c.url),
      );
      expect(rejectCall).toBeTruthy();
    });

    // Audit trail is rendered for the asset.
    expect(screen.getByTestId('audit-trail')).toBeInTheDocument();
  });
});
