import { describe, it, expect, afterEach, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ControlRoom } from './ControlRoom';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useDashboardStore } from '../state/store';

const FIXED_NOW = new Date('2026-07-17T07:00:00Z');

describe('ControlRoom display mode', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ displayMode: 'standard' });
  });

  it('matches the large-format KPI snapshot (production slide)', async () => {
    mock = installFetchMock();
    const { container } = renderWithProviders(
      <ControlRoom autoRotateMs={0} initialSlide={0} now={FIXED_NOW} />,
    );

    await waitFor(() => expect(screen.getByTestId('control-room-slide')).toBeInTheDocument());
    expect(screen.getByTestId('control-room-slide')).toHaveAttribute('data-slide', 'production');
    expect(container.firstChild).toMatchSnapshot();
  });

  it('auto-rotates through KPI views on the configured interval', async () => {
    vi.useFakeTimers();
    try {
      mock = installFetchMock();
      renderWithProviders(<ControlRoom autoRotateMs={5000} initialSlide={0} now={FIXED_NOW} />);

      // Let the mocked fetch resolve and the first slide render.
      await vi.waitFor(() =>
        expect(screen.getByTestId('control-room-slide')).toHaveAttribute('data-slide', 'production'),
      );

      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.getByTestId('control-room-slide')).toHaveAttribute('data-slide', 'health');

      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.getByTestId('control-room-slide')).toHaveAttribute('data-slide', 'energy');
    } finally {
      vi.useRealTimers();
    }
  });

  it('exits back to standard display mode', async () => {
    mock = installFetchMock();
    useDashboardStore.setState({ displayMode: 'control-room' });
    renderWithProviders(<ControlRoom autoRotateMs={0} now={FIXED_NOW} />);

    await userEvent.click(screen.getByTestId('control-room-exit'));
    expect(useDashboardStore.getState().displayMode).toBe('standard');
  });
});
