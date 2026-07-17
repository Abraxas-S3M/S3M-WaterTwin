import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ShiftReport } from './ShiftReport';
import { installFetchMock, renderWithProviders } from '../../test/utils';
import { useDashboardStore } from '../../state/store';

const GENERATED_AT = new Date('2026-07-17T07:00:00Z');

describe('ShiftReport print view', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ reportView: null });
  });

  it('matches the paginated shift-report snapshot', async () => {
    mock = installFetchMock();
    const { container } = renderWithProviders(
      <ShiftReport generatedAt={GENERATED_AT} onPrint={() => {}} />,
    );

    await waitFor(() => expect(screen.getByTestId('shift-kpis')).toBeInTheDocument());
    // Wait for the second-page data (energy) to load too before snapshotting.
    await waitFor(() => expect(screen.getByTestId('shift-energy')).toBeInTheDocument());
    expect(container.firstChild).toMatchSnapshot();
  });

  it('shows the mandatory advisory boundary footer', async () => {
    mock = installFetchMock();
    renderWithProviders(<ShiftReport generatedAt={GENERATED_AT} onPrint={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('report-boundary')).toBeInTheDocument());
    expect(screen.getByTestId('report-boundary')).toHaveTextContent(/no control write/i);
  });

  it('invokes the print handler and closes the report', async () => {
    mock = installFetchMock();
    useDashboardStore.setState({ reportView: 'shift' });
    const onPrint = vi.fn();
    renderWithProviders(<ShiftReport generatedAt={GENERATED_AT} onPrint={onPrint} />);

    await waitFor(() => expect(screen.getByTestId('shift-report')).toBeInTheDocument());

    await userEvent.click(screen.getByTestId('report-print'));
    expect(onPrint).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByTestId('report-close'));
    expect(useDashboardStore.getState().reportView).toBeNull();
  });
});
