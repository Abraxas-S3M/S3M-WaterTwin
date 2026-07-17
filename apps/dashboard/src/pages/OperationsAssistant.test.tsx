import { describe, it, expect, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OperationsAssistant } from './OperationsAssistant';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('OperationsAssistant', () => {
  let mock: ReturnType<typeof installFetchMock>;
  afterEach(() => mock?.restore());

  it('renders example prompt chips and an empty state before asking', async () => {
    mock = installFetchMock();
    renderWithProviders(<OperationsAssistant />);

    await waitFor(() =>
      expect(screen.getByTestId('operations-assistant')).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId('example-explain_degradation')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('assistant-empty')).toBeInTheDocument();
  });

  it('asks a question and renders the answer with its full evidence block', async () => {
    mock = installFetchMock();
    renderWithProviders(<OperationsAssistant />);

    await waitFor(() =>
      expect(screen.getByTestId('example-explain_degradation')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId('example-explain_degradation'));

    // The POST fired against the assistant endpoint.
    await waitFor(() => {
      const call = mock.calls.find(
        (c) => c.method === 'POST' && /\/assistant\/ask$/.test(c.url),
      );
      expect(call).toBeTruthy();
    });

    // The answer is rendered.
    await waitFor(() => expect(screen.getByTestId('assistant-answer')).toBeInTheDocument());
    expect(screen.getByTestId('assistant-answer')).toHaveTextContent(/health/i);

    // The full evidence block is always shown.
    const evidence = screen.getByTestId('assistant-evidence');
    expect(evidence).toBeInTheDocument();
    expect(screen.getByTestId('evidence-data-timestamp')).toBeInTheDocument();
    expect(screen.getByTestId('evidence-confidence')).toBeInTheDocument();
    expect(within(screen.getByTestId('evidence-assets')).getByText('AST-HPP-01')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('evidence-documents')).getByText('MAN-HPP-001'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('evidence-assumptions')).toBeInTheDocument();
    // Simulations-used field is present (empty here).
    expect(screen.getByTestId('evidence-simulations')).toHaveTextContent(/none/i);

    // Source-engine status (quad-engine vs local fallback) is visible.
    const engineBadges = screen.getAllByTestId('engine-status');
    expect(engineBadges[0]).toHaveAttribute('data-engine-status', 'fallback_local');

    // The recommended action is approvable via the existing flow.
    expect(screen.getByTestId('assistant-recommendation')).toBeInTheDocument();
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
  });

  it('approves the recommended action through the existing decision flow', async () => {
    mock = installFetchMock();
    renderWithProviders(<OperationsAssistant />);

    await waitFor(() =>
      expect(screen.getByTestId('example-explain_degradation')).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId('example-explain_degradation'));
    await waitFor(() => expect(screen.getByTestId('approve-button')).toBeInTheDocument());

    await userEvent.click(screen.getByTestId('approve-button'));
    await waitFor(() => {
      const call = mock.calls.find(
        (c) => c.method === 'POST' && /\/recommendations\/.+\/approve$/.test(c.url),
      );
      expect(call).toBeTruthy();
    });
  });

  it('shows the SafetyBoundaryBanner alongside the page', async () => {
    mock = installFetchMock();
    renderWithProviders(
      <>
        <SafetyBoundaryBanner />
        <OperationsAssistant />
      </>,
    );
    expect(screen.getByTestId('safety-boundary-banner')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('operations-assistant')).toBeInTheDocument(),
    );
  });
});
