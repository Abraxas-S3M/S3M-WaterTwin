import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
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
  });
});
