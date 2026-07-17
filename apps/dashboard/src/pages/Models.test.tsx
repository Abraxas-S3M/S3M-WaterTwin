import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Models } from './Models';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('Models & Compliance', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders the model registry and compliance panels from a mocked API', async () => {
    mock = installFetchMock();
    renderWithProviders(<Models />);

    await waitFor(() => expect(screen.getByTestId('models')).toBeInTheDocument());

    // Registry table with versions, tracks and drift status.
    expect(screen.getByTestId('models-registry')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('model-row-water-quality-ro')).toBeInTheDocument(),
    );
    expect(screen.getByText('1.3.0')).toBeInTheDocument();
    const driftBadges = screen.getAllByTestId('drift-badge');
    expect(driftBadges.some((b) => b.getAttribute('data-drift') === 'drifting')).toBe(true);

    // Compliance panel: configured limits + a flagged exceedance.
    expect(screen.getByTestId('compliance-panel')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('exceedance-row-conductivity_us_cm')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('limit-row-turbidity_ntu')).toBeInTheDocument();
    expect(screen.getByTestId('compliance-overall')).toHaveTextContent(/exceedance/i);

    // Provenance is visible (nothing presented as validated).
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('generates a downloadable compliance report on demand', async () => {
    mock = installFetchMock();
    renderWithProviders(<Models />);

    await waitFor(() =>
      expect(screen.getByTestId('generate-compliance-report')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId('generate-compliance-report'));

    await waitFor(() =>
      expect(screen.getByTestId('compliance-report-preview')).toBeInTheDocument(),
    );
    const reportCall = mock.calls.find(
      (c) => c.method === 'POST' && /\/reports\/compliance$/.test(c.url),
    );
    expect(reportCall).toBeTruthy();
  });
});
