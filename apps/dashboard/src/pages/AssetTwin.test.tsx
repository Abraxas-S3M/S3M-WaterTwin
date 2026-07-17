import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

    // Health + contribution breakdown
    await waitFor(() => expect(screen.getByTestId('health-bar')).toBeInTheDocument());
    expect(screen.getByTestId('contribution-breakdown')).toBeInTheDocument();
    expect(screen.getByText('Vibration trend')).toBeInTheDocument();

    // Anomaly domains
    await waitFor(() => expect(screen.getByText('Mechanical')).toBeInTheDocument());

    // Live telemetry
    await waitFor(() => expect(screen.getByText('Flow M3h')).toBeInTheDocument());

    // Recommendation present with approve/reject controls
    await waitFor(() => expect(screen.getByTestId('recommendation-card')).toBeInTheDocument());
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
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
