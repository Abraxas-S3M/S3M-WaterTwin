import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Administration } from './Administration';
import { installFetchMock, renderWithProviders } from '../test/utils';
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
