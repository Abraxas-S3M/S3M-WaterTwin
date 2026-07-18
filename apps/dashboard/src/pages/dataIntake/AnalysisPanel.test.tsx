import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnalysisPanel, type AnalysisResult, type ProposedChange } from './AnalysisPanel';

function makeChange(overrides: Partial<ProposedChange> = {}): ProposedChange {
  return {
    change_id: 'ING-001:draft:pump.P-003.rated_efficiency_pct:0',
    field_path: 'pump.P-003.rated_efficiency_pct',
    current_value: null,
    proposed_value: 78.0,
    provenance: 'preliminary',
    ai_suggested: true,
    ai_confidence: 0.55,
    ai_rationale: 'Inferred from the curve shape near best-efficiency point.',
    citation: { document_id: 'ING-001', locator: 'rows 2-4' },
    accepted: false,
    accepted_by: null,
    accepted_at: null,
    ...overrides,
  };
}

function makeAnalysis(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return {
    ingest_id: 'ING-001',
    parse_result_hash: 'abc123',
    available: true,
    notice: null,
    model_version: 's3m-core-analysis@2026.07.1',
    source_engine_status: 'quad-engine',
    generated_at: '2026-07-18T08:00:00Z',
    summary: {
      text: 'Head-flow pump curve for P-003 with three operating points.',
      confidence: 0.8,
      rationale: 'Parsed a 3-point head/flow table plus a nameplate note.',
      citation: { document_id: 'ING-001', locator: 'rows 2-5' },
    },
    anomalies: [
      {
        code: 'curve-vs-nameplate',
        message: "pump P-003's curve implies 18% higher duty than its nameplate",
        severity: 'warning',
        confidence: 0.72,
        rationale: 'Head at rated flow exceeds the nameplate duty point by ~18%.',
        citation: { document_id: 'ING-001', locator: 'row 4 (curve) vs nameplate note' },
        cross_references: ['AST-HPP-03'],
      },
    ],
    drafted_values: [
      {
        field_path: 'pump.P-003.rated_efficiency_pct',
        value: 78.0,
        confidence: 0.55,
        rationale: 'Inferred from the curve shape.',
        citation: { document_id: 'ING-001', locator: 'rows 2-4' },
      },
    ],
    proposed_changes: [makeChange()],
    ...overrides,
  };
}

describe('AnalysisPanel', () => {
  afterEach(() => cleanup());

  it('renders summary, a cited anomaly flag, and AI-drafted diff rows', () => {
    render(<AnalysisPanel analysis={makeAnalysis()} />);

    expect(screen.getByTestId('analysis-panel')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-summary')).toHaveTextContent(/pump curve/i);

    // Acceptance criterion: the curve-vs-nameplate anomaly is visible + cited.
    const anomaly = screen.getByTestId('anomaly-curve-vs-nameplate');
    expect(anomaly).toHaveTextContent(/nameplate/i);
    expect(within(anomaly).getByTestId('citation')).toHaveTextContent('ING-001');
    expect(within(anomaly).getByTestId('anomaly-cross-refs')).toHaveTextContent('AST-HPP-03');

    // The model version is surfaced for traceability.
    expect(screen.getByTestId('analysis-model-version')).toHaveTextContent(
      's3m-core-analysis@2026.07.1',
    );
  });

  it('shows AI-suggested changes as visually distinct rows that DEFAULT TO UNACCEPTED', () => {
    render(<AnalysisPanel analysis={makeAnalysis()} />);

    const row = screen.getByTestId('ai-change-pump.P-003.rated_efficiency_pct');
    // Visually distinct: badged as AI-suggested and marked in the row dataset.
    expect(within(row).getByTestId('ai-badge')).toBeInTheDocument();
    expect(row).toHaveAttribute('data-ai-suggested', 'true');
    expect(row).toHaveClass('ai-suggested');

    // Nothing is pre-checked: the opt-in checkbox is unchecked by default.
    const checkbox = screen.getByTestId('accept-pump.P-003.rated_efficiency_pct');
    expect(checkbox).not.toBeChecked();
    expect(row).toHaveAttribute('data-accepted', 'false');
  });

  it('requires an explicit per-field opt-in via the checkbox', async () => {
    const onAcceptChange = vi.fn();
    render(<AnalysisPanel analysis={makeAnalysis()} onAcceptChange={onAcceptChange} />);

    const checkbox = screen.getByTestId('accept-pump.P-003.rated_efficiency_pct');
    await userEvent.click(checkbox);

    expect(onAcceptChange).toHaveBeenCalledTimes(1);
    const [change, accepted] = onAcceptChange.mock.calls[0];
    expect(change.field_path).toBe('pump.P-003.rated_efficiency_pct');
    expect(accepted).toBe(true);
  });

  it('reflects an accepted change only when acceptance state says so', () => {
    render(
      <AnalysisPanel
        analysis={makeAnalysis()}
        acceptedFields={{ 'pump.P-003.rated_efficiency_pct': true }}
      />,
    );
    expect(screen.getByTestId('accept-pump.P-003.rated_efficiency_pct')).toBeChecked();
  });

  it('never shows an AI-drafted value labelled measured (provenance clamped)', () => {
    render(<AnalysisPanel analysis={makeAnalysis()} />);
    const badge = screen.getByTestId('change-provenance');
    expect(badge).toHaveAttribute('data-provenance', 'preliminary');
    expect(badge).not.toHaveAttribute('data-provenance', 'measured');
  });

  it('degrades gracefully: unavailable analysis renders a quiet notice, no panel', () => {
    render(
      <AnalysisPanel
        analysis={makeAnalysis({
          available: false,
          notice: 'AI analysis is temporarily unavailable.',
          summary: null,
          anomalies: [],
          drafted_values: [],
          proposed_changes: [],
        })}
      />,
    );
    expect(screen.getByTestId('analysis-unavailable-notice')).toBeInTheDocument();
    expect(screen.queryByTestId('analysis-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('diff-table')).not.toBeInTheDocument();
  });

  it('renders nothing when analysis is absent', () => {
    const { container } = render(<AnalysisPanel analysis={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('analysis-panel')).not.toBeInTheDocument();
  });
});
