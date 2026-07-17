import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MaintenanceCenter } from './MaintenanceCenter';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useDashboardStore } from '../state/store';

describe('MaintenanceCenter', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ selectedAssetId: null, page: 'command' });
  });

  it('renders work orders derived from PdM alerts with CMMS read-only status', async () => {
    mock = installFetchMock();
    renderWithProviders(<MaintenanceCenter />);

    await waitFor(() =>
      expect(screen.getByTestId('maintenance-center')).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByTestId('work-order-table')).toBeInTheDocument());

    expect(screen.getByText('High-Pressure Pump A')).toBeInTheDocument();
    // Traceable to the originating PdM alert.
    expect(screen.getByText('PDM-AST-HPP-01')).toBeInTheDocument();
    // CMMS status is surfaced as read-only.
    expect(screen.getByTestId('cmms-status')).toHaveTextContent(/read-only/i);
  });

  it('shows the alert -> work order -> approval -> audit traceability flow', async () => {
    mock = installFetchMock();
    renderWithProviders(<MaintenanceCenter />);

    await waitFor(() => expect(screen.getByTestId('work-order-detail')).toBeInTheDocument());
    const flow = screen.getByTestId('traceability-flow');
    expect(flow).toHaveTextContent(/PdM alert/i);
    expect(flow).toHaveTextContent(/Proposed work order/i);
    expect(flow).toHaveTextContent(/Operator approval/i);
    expect(flow).toHaveTextContent(/Audit entry/i);
  });

  it('round-trips an operator approval on a work order', async () => {
    mock = installFetchMock();
    renderWithProviders(<MaintenanceCenter />);

    await waitFor(() => expect(screen.getByTestId('approve-work-order')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('approve-work-order'));

    await waitFor(() => {
      const call = mock.calls.find(
        (c) =>
          c.method === 'POST' && /\/maintenance\/work-orders\/.+\/decision$/.test(c.url),
      );
      expect(call).toBeTruthy();
      expect((call?.body as { status?: string })?.status).toBe('approved');
    });
  });
});
