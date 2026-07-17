import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { SafetyBoundaryBanner } from './SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('SafetyBoundaryBanner', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => mock?.restore());

  it('renders the advisory / no-write banner', async () => {
    mock = installFetchMock();
    renderWithProviders(<SafetyBoundaryBanner />);

    const banner = screen.getByTestId('safety-boundary-banner');
    expect(banner).toBeInTheDocument();
    expect(screen.getByText(/NO CONTROL WRITE/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/does not write to plant controls/i)).toBeInTheDocument();
    });
  });
});
