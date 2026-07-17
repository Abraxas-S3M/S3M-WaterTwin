import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { FleetRollup } from './FleetRollup';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useAuthStore } from '../auth/store';
import { fleetOverview, TENANT_ACME, TENANT_GLOBEX } from '../test/fixtures';

function setScope(roles: string[], facilityIds: string[], tenantId: string | null = TENANT_ACME) {
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

describe('FleetRollup', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    setScope(['tenant-admin'], []);
  });

  it('rolls up health / energy / alerts across all facilities for a tenant-admin', async () => {
    setScope(['tenant-admin'], []);
    mock = installFetchMock();
    renderWithProviders(<FleetRollup />);

    await waitFor(() => expect(screen.getByTestId('fleet-overview')).toBeInTheDocument());

    // Per-facility rows.
    expect(screen.getByTestId('fleet-row-FAC-ALPHA')).toBeInTheDocument();
    expect(screen.getByTestId('fleet-row-FAC-BETA')).toBeInTheDocument();
    expect(screen.getByTestId('fleet-row-FAC-GAMMA')).toBeInTheDocument();

    // Aggregate KPIs.
    expect(screen.getByText('Facilities Online')).toBeInTheDocument();
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    // Total power 1520 + 980 + 1750 = 4,250 kW.
    expect(screen.getByText('4,250')).toBeInTheDocument();
    // Total alarms 1 + 3 + 0 = 4.
    expect(screen.getByText('Fleet Active Alarms')).toBeInTheDocument();
    expect(screen.getByText('Worst band: Degraded')).toBeInTheDocument();
  });

  it('scopes the roll-up to a single facility for a facility-operator', async () => {
    setScope(['facility-operator'], ['FAC-ALPHA']);
    mock = installFetchMock();
    renderWithProviders(<FleetRollup />);

    await waitFor(() => expect(screen.getByTestId('fleet-overview')).toBeInTheDocument());

    expect(screen.getByTestId('fleet-row-FAC-ALPHA')).toBeInTheDocument();
    expect(screen.queryByTestId('fleet-row-FAC-BETA')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fleet-row-FAC-GAMMA')).not.toBeInTheDocument();

    // Aggregates reflect only the scoped facility (1 facility, 1,520 kW). The
    // value appears in both the Fleet Power KPI and the single facility row.
    expect(screen.getByText('1 / 1')).toBeInTheDocument();
    expect(screen.getAllByText('1,520').length).toBeGreaterThanOrEqual(2);
  });

  it('excludes a foreign-tenant facility from both rows and totals', async () => {
    setScope(['tenant-admin'], []);
    mock = installFetchMock({
      fleetOverview: {
        ...fleetOverview,
        facilities: [
          ...fleetOverview.facilities,
          {
            facility_id: 'FAC-OMEGA',
            tenant_id: TENANT_GLOBEX,
            name: 'SWRO Omega',
            status: 'online',
            health: { score: 5, band: 'Critical' },
            energy: { total_power_kw: 9999, specific_energy_kwh_m3: 5 },
            active_alarms: 99,
            production_m3_day: 20000,
            provenance: 'preliminary',
          },
        ],
      },
    });
    renderWithProviders(<FleetRollup />);

    await waitFor(() => expect(screen.getByTestId('fleet-overview')).toBeInTheDocument());

    expect(screen.queryByTestId('fleet-row-FAC-OMEGA')).not.toBeInTheDocument();
    expect(screen.queryByText('SWRO Omega')).not.toBeInTheDocument();
    // Totals must be unaffected by the foreign facility's 9,999 kW / 99 alarms.
    const table = screen.getByTestId('fleet-table');
    expect(within(table).queryByText('9,999')).not.toBeInTheDocument();
    expect(screen.getByText('4,250')).toBeInTheDocument();
    // Worst band stays Degraded (Critical foreign row excluded).
    expect(screen.getByText('Worst band: Degraded')).toBeInTheDocument();
  });
});
