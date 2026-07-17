import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExecutiveReport } from './ExecutiveReport';
import { installFetchMock, renderWithProviders } from '../../test/utils';
import { useDashboardStore } from '../../state/store';

const GENERATED_AT = new Date('2026-07-17T07:00:00Z');

describe('ExecutiveReport print view', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ reportView: null });
  });

  it('matches the paginated executive-report snapshot', async () => {
    mock = installFetchMock();
    const { container } = renderWithProviders(
      <ExecutiveReport generatedAt={GENERATED_AT} onPrint={() => {}} />,
    );

    await waitFor(() => expect(screen.getByTestId('executive-report-benefits')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('executive-report-roi')).toBeInTheDocument());
    expect(container.firstChild).toMatchSnapshot();
  });

  it('always shows the ESTIMATED/synthetic disclaimer and advisory footer', async () => {
    mock = installFetchMock();
    renderWithProviders(<ExecutiveReport generatedAt={GENERATED_AT} onPrint={() => {}} />);

    await waitFor(() =>
      expect(screen.getByTestId('executive-report-disclaimer')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('executive-report-disclaimer')).toHaveTextContent(
      /not validated savings/i,
    );
    expect(screen.getByTestId('report-boundary')).toHaveTextContent(/advisory/i);
  });

  it('invokes the print handler and closes the report', async () => {
    mock = installFetchMock();
    useDashboardStore.setState({ reportView: 'executive' });
    const onPrint = vi.fn();
    renderWithProviders(<ExecutiveReport generatedAt={GENERATED_AT} onPrint={onPrint} />);

    await waitFor(() => expect(screen.getByTestId('executive-report')).toBeInTheDocument());

    await userEvent.click(screen.getByTestId('report-print'));
    expect(onPrint).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByTestId('report-close'));
    expect(useDashboardStore.getState().reportView).toBeNull();
  });
});
