import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TrainingSimulator } from './TrainingSimulator';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('TrainingSimulator', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('shows the SIMULATION disclaimer and the available drills', async () => {
    mock = installFetchMock();
    renderWithProviders(<TrainingSimulator />);

    await waitFor(() => expect(screen.getByTestId('training-simulator')).toBeInTheDocument());

    // Clearly labeled SIMULATION with the "cannot emit any command" guarantee.
    const disclaimer = screen.getByTestId('training-disclaimer');
    expect(disclaimer).toHaveTextContent(/SIMULATION/i);
    expect(disclaimer).toHaveTextContent(/cannot emit any command/i);

    await waitFor(() =>
      expect(screen.getByTestId('start-drill-pump-degradation')).toBeInTheDocument(),
    );
  });

  it('injects a scenario and renders the simulated twin snapshot', async () => {
    mock = installFetchMock();
    renderWithProviders(<TrainingSimulator />);

    await waitFor(() =>
      expect(screen.getByTestId('start-drill-pump-degradation')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId('start-drill-pump-degradation'));

    // The scenario-injection POST fired.
    await waitFor(() => {
      const call = mock.calls.find(
        (c) => c.method === 'POST' && /\/training\/sessions$/.test(c.url),
      );
      expect(call).toBeTruthy();
    });

    await waitFor(() => expect(screen.getByTestId('training-twin')).toBeInTheDocument());
    // Injected telemetry is tagged simulated (never presented as measured plant data).
    const badges = screen.getAllByTestId('provenance-badge');
    expect(badges.some((b) => b.getAttribute('data-provenance') === 'simulated')).toBe(true);
    expect(screen.getByTestId('injected-telemetry')).toBeInTheDocument();
  });

  it('captures a sandboxed action and scores the drill', async () => {
    mock = installFetchMock();
    renderWithProviders(<TrainingSimulator />);

    await userEvent.click(await screen.findByTestId('start-drill-pump-degradation'));
    await waitFor(() => expect(screen.getByTestId('action-capture')).toBeInTheDocument());

    await userEvent.type(
      screen.getByTestId('training-action-text'),
      'Rising vibration and bearing wear; schedule a maintenance inspection.',
    );
    await userEvent.click(screen.getByTestId('capture-action'));

    // The action-capture POST fired and the captured action is shown as "no command".
    await waitFor(() => {
      const call = mock.calls.find(
        (c) => c.method === 'POST' && /\/training\/sessions\/.+\/actions$/.test(c.url),
      );
      expect(call).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByTestId('captured-actions')).toHaveTextContent('no command'));

    await userEvent.click(screen.getByTestId('submit-drill'));
    await waitFor(() => expect(screen.getByTestId('training-score')).toBeInTheDocument());
    expect(screen.getByTestId('training-score')).toHaveTextContent('Exemplary');
  });

  it('renders alongside the SafetyBoundaryBanner', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <TrainingSimulator />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('training-simulator')).toBeInTheDocument());
  });
});
