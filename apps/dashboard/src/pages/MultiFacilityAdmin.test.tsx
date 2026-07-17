import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MultiFacilityAdmin } from './MultiFacilityAdmin';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useAuthStore } from '../auth/store';
import { TENANT_ACME } from '../test/fixtures';

function setScope(roles: string[], facilityIds: string[], tenantId = TENANT_ACME) {
  useAuthStore.setState({
    status: 'authenticated',
    username: 'test-user',
    roles,
    tenantId,
    facilityIds,
    accessToken: 't',
    refreshToken: null,
    expiresAt: null,
    error: null,
  });
}

describe('MultiFacilityAdmin', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    setScope(['tenant-admin'], []);
  });

  it('lists facilities and per-facility config + roles for a tenant-admin', async () => {
    setScope(['tenant-admin'], []);
    mock = installFetchMock();
    renderWithProviders(<MultiFacilityAdmin />);

    await waitFor(() => expect(screen.getByTestId('multi-facility-admin')).toBeInTheDocument());

    // Every facility in the tenant is listed.
    expect(screen.getByTestId('admin-facility-row-FAC-ALPHA')).toBeInTheDocument();
    expect(screen.getByTestId('admin-facility-row-FAC-BETA')).toBeInTheDocument();
    expect(screen.getByTestId('admin-facility-row-FAC-GAMMA')).toBeInTheDocument();

    // Default detail shows the first facility's config + roles.
    const detail = screen.getByTestId('admin-facility-detail');
    expect(detail).toHaveTextContent('SWRO Alpha');
    expect(screen.getByTestId('admin-facility-roles')).toBeInTheDocument();
    expect(screen.getByText('Ola Operator')).toBeInTheDocument();

    // Selecting another facility swaps the detail + its role assignments.
    await userEvent.click(screen.getByTestId('admin-facility-row-FAC-GAMMA'));
    await waitFor(() =>
      expect(screen.getByTestId('admin-facility-detail')).toHaveTextContent('SWRO Gamma'),
    );
    expect(screen.getByText('Gia Engineer')).toBeInTheDocument();
  });

  it('forbids a facility-operator from the fleet-wide administration surface', async () => {
    setScope(['facility-operator'], ['FAC-ALPHA']);
    mock = installFetchMock();
    renderWithProviders(<MultiFacilityAdmin />);

    expect(screen.getByTestId('admin-facilities-forbidden')).toBeInTheDocument();
    // The tenant's facility list must not render for an unauthorized role.
    expect(screen.queryByTestId('admin-facilities-table')).not.toBeInTheDocument();
  });
});
