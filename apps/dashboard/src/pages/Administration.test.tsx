import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Administration } from './Administration';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('Administration', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  beforeEach(() => {
    // jsdom has no object-URL / navigation; stub them for the download path.
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  it('renders entitlements, usage, and the signed-update channel', async () => {
import { useAuthStore } from '../auth/store';
import { ALL_ROLES } from '../auth/roles';

function setRoles(roles: string[]) {
  useAuthStore.setState({
    status: 'authenticated',
    username: 'test-user',
    roles,
    accessToken: 't',
    refreshToken: null,
    expiresAt: null,
    error: null,
  });
}

describe('Administration / Configuration Workbench', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => {
    mock?.restore();
    setRoles([...ALL_ROLES]);
  });

  it('renders every panel via the tab strip for an admin', async () => {
    setRoles(['admin']);
    mock = installFetchMock();
    renderWithProviders(<Administration />);

    await waitFor(() => expect(screen.getByTestId('administration')).toBeInTheDocument());

    // Licensing / entitlements: plan + safety-invariant assurance.
    expect(screen.getByTestId('admin-entitlements')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('safety-invariant-chip')).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/enterprise/i).length).toBeGreaterThan(0);

    // Usage metering counts are surfaced.
    expect(screen.getByTestId('admin-usage')).toBeInTheDocument();

    // Signed-update channel: auto-update disabled, verify-before-apply true.
    await waitFor(() => expect(screen.getByTestId('admin-update-channel')).toBeInTheDocument());
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.getByTestId('update-policy')).toBeInTheDocument();
  });

  it('generates a support bundle on demand', async () => {
    mock = installFetchMock();
    renderWithProviders(<Administration />);

    await waitFor(() => expect(screen.getByTestId('generate-bundle')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('generate-bundle'));

    await waitFor(() => expect(screen.getByTestId('bundle-status')).toBeInTheDocument());
    const bundleCall = mock.calls.find(
      (c) => c.method === 'POST' && /\/admin\/support\/bundle$/.test(c.url),
    );
    expect(bundleCall).toBeTruthy();
    expect(screen.getByTestId('admin-workflow-strip')).toBeInTheDocument();

    // Default panel (asset hierarchy) renders.
    expect(screen.getByTestId('admin-panel-asset-hierarchy')).toBeInTheDocument();

    // Each remaining panel is reachable via its tab.
    const tabPanels: [string, string][] = [
      ['admin-tab-tag-mapping', 'admin-panel-tag-mapping'],
      ['admin-tab-alarm-thresholds', 'admin-panel-alarm-thresholds'],
      ['admin-tab-rated-equipment', 'admin-panel-rated-equipment'],
      ['admin-tab-process-stages', 'admin-panel-process-stages'],
      ['admin-tab-lab-methods', 'admin-panel-lab-methods'],
      ['admin-tab-user-roles', 'admin-panel-user-roles'],
    ];
    for (const [tab, panel] of tabPanels) {
      await userEvent.click(screen.getByTestId(tab));
      expect(screen.getByTestId(panel)).toBeInTheDocument();
    }
  });

  it('shows the approve control for an admin and round-trips the approve action', async () => {
    setRoles(['admin']);
    mock = installFetchMock();
    renderWithProviders(<Administration />);

    await waitFor(() => expect(screen.getByTestId('admin-approve-button')).toBeInTheDocument());
    const approve = screen.getByTestId('admin-approve-button');
    expect(approve).toBeEnabled();
    await userEvent.click(approve);

    await waitFor(() => {
      const approveCall = mock.calls.find(
        (c) => c.method === 'POST' && /\/config\/approve$/.test(c.url),
      );
      expect(approveCall).toBeTruthy();
    });
  });

  it('round-trips a draft save after an edit', async () => {
    setRoles(['admin']);
    mock = installFetchMock();
    renderWithProviders(<Administration />);

    await waitFor(() => expect(screen.getByTestId('admin-panel-asset-hierarchy')).toBeInTheDocument());
    const saveButton = screen.getByTestId('admin-save-draft-button');
    expect(saveButton).toBeDisabled();

    await userEvent.type(screen.getByLabelText('asset-name-0'), '!');
    expect(saveButton).toBeEnabled();
    await userEvent.click(saveButton);

    await waitFor(() => {
      const putCall = mock.calls.find((c) => c.method === 'PUT' && /\/config\/draft$/.test(c.url));
      expect(putCall).toBeTruthy();
    });
  });

  it('is read-only and gates approval for a non-admin role', async () => {
    setRoles(['operator']);
    mock = installFetchMock();
    renderWithProviders(<Administration />);

    await waitFor(() => expect(screen.getByTestId('administration')).toBeInTheDocument());

    // No approve control; a role gate + read-only note instead.
    expect(screen.queryByTestId('admin-approve-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('admin-approve-role-gate')).toBeInTheDocument();
    expect(screen.getByTestId('admin-readonly-note')).toBeInTheDocument();

    // Inputs are disabled and add affordances are hidden.
    expect(screen.getByLabelText('asset-id-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-asset-hierarchy-add')).not.toBeInTheDocument();
  });
});
