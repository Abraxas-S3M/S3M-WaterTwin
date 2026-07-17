import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Security } from './Security';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';
import * as fx from '../test/fixtures';

describe('Security', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders every security panel from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<Security />);

    await waitFor(() => expect(screen.getByTestId('security')).toBeInTheDocument());

    // All panels present.
    expect(screen.getByTestId('security-kpis')).toBeInTheDocument();
    expect(screen.getByTestId('audit-integrity')).toBeInTheDocument();
    expect(screen.getByTestId('source-health')).toBeInTheDocument();
    expect(screen.getByTestId('sensor-confidence')).toBeInTheDocument();
    expect(screen.getByTestId('cyber-physical-consistency')).toBeInTheDocument();
    expect(screen.getByTestId('siem-export')).toBeInTheDocument();

    expect(screen.getByRole('heading', { name: /Cyber-Physical Security/i })).toBeInTheDocument();

    // Data from fixtures surfaced: per-asset rows and an inconsistent signal.
    await waitFor(() =>
      expect(screen.getByTestId('confidence-row-AST-HPP-01')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('consistency-row-AST-HPP-01')).toBeInTheDocument();
    expect(screen.getAllByText(/verified/i).length).toBeGreaterThan(0);

    // The audit-chain verify status is surfaced (integrity is intact here).
    const auditPanel = screen.getByTestId('audit-integrity');
    expect(auditPanel).toHaveTextContent(/verified/i);

    // Nothing presented as validated: preliminary provenance visible.
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'preliminary')).toBe(true);
  });

  it('surfaces a broken audit chain and an alert posture', async () => {
    mock = installFetchMock({
      securityOverview: {
        ...fx.securityOverview,
        status: 'alert',
        audit_integrity: {
          ok: false,
          count: 3,
          broken_at: 'evt-2',
          index: 1,
          reason: 'hash mismatch (event contents were altered)',
        },
      },
    });
    renderWithProviders(<Security />);

    await waitFor(() => expect(screen.getByTestId('audit-broken-at')).toBeInTheDocument());
    expect(screen.getByTestId('audit-broken-at')).toHaveTextContent('evt-2');
    expect(screen.getByTestId('audit-integrity')).toHaveTextContent(/broken/i);
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <Security />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('security')).toBeInTheDocument());
  });

  it('exports a signed SIEM feed on demand and surfaces the signature', async () => {
    mock = installFetchMock();
    renderWithProviders(<Security />);

    await waitFor(() => expect(screen.getByTestId('siem-export-json')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('siem-export-json'));

    await waitFor(() => expect(screen.getByTestId('siem-export-result')).toBeInTheDocument());
    expect(screen.getByTestId('siem-signature')).toBeInTheDocument();

    const exportCall = mock.calls.find(
      (c) => c.method === 'GET' && /\/security\/siem-export/.test(c.url),
    );
    expect(exportCall).toBeTruthy();
  });
});
