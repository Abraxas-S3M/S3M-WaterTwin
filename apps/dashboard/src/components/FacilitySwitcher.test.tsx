import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FacilitySwitcher } from './FacilitySwitcher';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useAuthStore } from '../auth/store';
import { useDashboardStore } from '../state/store';
import {
  acmeFacilities,
  facilityOmegaForeign,
  facilitiesResponse,
  TENANT_ACME,
} from '../test/fixtures';

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

describe('FacilitySwitcher', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ activeFacilityId: null });
    setScope(['tenant-admin'], []);
  });

  it('lists every facility in the tenant for a tenant-admin', async () => {
    setScope(['tenant-admin'], []);
    mock = installFetchMock();
    renderWithProviders(<FacilitySwitcher />);

    await waitFor(() =>
      expect(screen.getByTestId('facility-switcher-select')).toBeInTheDocument(),
    );
    for (const f of acmeFacilities) {
      expect(screen.getByTestId(`facility-option-${f.facility_id}`)).toBeInTheDocument();
    }
    // Defaults the active facility to the first visible one.
    await waitFor(() =>
      expect(useDashboardStore.getState().activeFacilityId).toBe('FAC-ALPHA'),
    );
  });

  it('shows only the assigned facility (no dropdown) for a facility-operator', async () => {
    setScope(['facility-operator'], ['FAC-ALPHA']);
    mock = installFetchMock();
    renderWithProviders(<FacilitySwitcher />);

    await waitFor(() =>
      expect(screen.getByTestId('facility-switcher-single')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('facility-switcher-single')).toHaveTextContent('SWRO Alpha');
    // No multi-facility dropdown, and the other facilities are absent from the DOM.
    expect(screen.queryByTestId('facility-switcher-select')).not.toBeInTheDocument();
    expect(screen.queryByText('SWRO Beta')).not.toBeInTheDocument();
    expect(screen.queryByText('SWRO Gamma')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(useDashboardStore.getState().activeFacilityId).toBe('FAC-ALPHA'),
    );
  });

  it('switches the active facility on selection', async () => {
    setScope(['tenant-admin'], []);
    mock = installFetchMock();
    renderWithProviders(<FacilitySwitcher />);

    await waitFor(() =>
      expect(screen.getByTestId('facility-switcher-select')).toBeInTheDocument(),
    );
    await userEvent.selectOptions(
      screen.getByTestId('facility-switcher-select'),
      'FAC-GAMMA',
    );
    expect(useDashboardStore.getState().activeFacilityId).toBe('FAC-GAMMA');
  });

  it('never renders a facility from another tenant, even if the API over-returns', async () => {
    setScope(['tenant-admin'], []);
    // Adversarial payload: a Globex facility mixed into the ACME response.
    mock = installFetchMock({
      facilities: {
        ...facilitiesResponse,
        facilities: [...acmeFacilities, facilityOmegaForeign],
      },
    });
    renderWithProviders(<FacilitySwitcher />);

    await waitFor(() =>
      expect(screen.getByTestId('facility-switcher-select')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('facility-option-FAC-OMEGA')).not.toBeInTheDocument();
    expect(screen.queryByText('SWRO Omega')).not.toBeInTheDocument();
  });
});
