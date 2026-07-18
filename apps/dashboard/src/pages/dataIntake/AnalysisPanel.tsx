import type { DataProvenance } from '../../api/types';

/**
 * AI-assisted analysis of a staged file. This panel is DECISION SUPPORT only:
 * it renders a plain-language summary, cited anomaly flags, and AI-drafted
 * values for fields the parser could not fill. Every AI-derived value is badged,
 * carries a confidence + citation, and DEFAULTS TO UNACCEPTED — a human must
 * opt in per field. The panel never accepts, approves, or commits anything.
 *
 * Graceful degradation: when analysis is absent or `available === false`, the
 * panel does not render its body — the surrounding proposal/diff still renders
 * normally, with only a quiet notice here.
 */

export interface AnalysisCitation {
  document_id: string;
  locator: string;
  snippet?: string | null;
}

export interface AnalysisSummary {
  text: string;
  confidence: number;
  rationale: string;
  citation: AnalysisCitation;
}

export interface AnomalyFlag {
  code: string;
  message: string;
  severity: string;
  confidence: number;
  rationale: string;
  citation: AnalysisCitation;
  cross_references: string[];
}

export interface DraftedValue {
  field_path: string;
  value: unknown;
  confidence: number;
  rationale: string;
  citation: AnalysisCitation;
}

export interface ProposedChange {
  change_id: string;
  field_path: string;
  current_value: unknown;
  proposed_value: unknown;
  provenance: DataProvenance;
  ai_suggested: boolean;
  ai_confidence: number | null;
  ai_rationale: string | null;
  citation: AnalysisCitation | null;
  accepted: boolean;
  accepted_by: string | null;
  accepted_at: string | null;
}

export interface AnalysisResult {
  ingest_id: string;
  parse_result_hash: string;
  available: boolean;
  notice?: string | null;
  model_version?: string | null;
  source_engine_status: string;
  generated_at: string;
  summary: AnalysisSummary | null;
  anomalies: AnomalyFlag[];
  drafted_values: DraftedValue[];
  proposed_changes: ProposedChange[];
}

export interface AnalysisPanelProps {
  /** The analysis result. `null`/`undefined` renders nothing (analysis absent). */
  analysis?: AnalysisResult | null;
  /** Whether an analysis request is in flight. */
  loading?: boolean;
  /** Per-field human opt-in state, keyed by `field_path`. Defaults to empty. */
  acceptedFields?: Record<string, boolean>;
  /** Called when a human toggles the per-field opt-in. */
  onAcceptChange?: (change: ProposedChange, accepted: boolean) => void;
}

const DEGRADED_NOTICE =
  'AI analysis is temporarily unavailable. The proposal below is complete and reviewable without it.';

function pct(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function display(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function Citation({ citation }: { citation: AnalysisCitation }) {
  return (
    <span className="card-sub" data-testid="citation">
      Source: <strong>{citation.document_id}</strong> — {citation.locator}
      {citation.snippet ? <em> ({citation.snippet})</em> : null}
    </span>
  );
}

function ProvenanceBadge({ provenance }: { provenance: DataProvenance }) {
  const validated = provenance === 'measured';
  return (
    <span
      className={`prov-badge ${validated ? 'validated' : 'unvalidated'}`}
      data-testid="change-provenance"
      data-provenance={provenance}
      title="Provenance of this value (AI drafts can never outrank the source file)."
    >
      {provenance}
    </span>
  );
}

export function AnalysisPanel({
  analysis,
  loading = false,
  acceptedFields = {},
  onAcceptChange,
}: AnalysisPanelProps) {
  if (loading) {
    return (
      <div className="card" data-testid="analysis-loading">
        <span className="muted">Analyzing staged file…</span>
      </div>
    );
  }

  // Analysis absent: render nothing so the diff remains the critical path.
  if (!analysis) return null;

  // Graceful degradation: no panel body, only a quiet notice.
  if (!analysis.available) {
    return (
      <div className="card" data-testid="analysis-unavailable-notice">
        <span className="muted">{analysis.notice ?? DEGRADED_NOTICE}</span>
      </div>
    );
  }

  const changes = analysis.proposed_changes;

  return (
    <div className="stack" data-testid="analysis-panel">
      <div className="card" data-testid="analysis-header">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>AI-assisted analysis</h3>
          <span className="status-chip" data-testid="ai-decision-support">
            Decision support — nothing accepted automatically
          </span>
        </div>
        <div className="card-sub" data-testid="analysis-model-version">
          Model: {analysis.model_version ?? 'unknown'} · Engine: {analysis.source_engine_status}
        </div>
      </div>

      {analysis.summary ? (
        <div className="card" data-testid="analysis-summary">
          <h4>Summary</h4>
          <p>{analysis.summary.text}</p>
          <div className="card-sub" data-testid="summary-confidence">
            Confidence {pct(analysis.summary.confidence)} · {analysis.summary.rationale}
          </div>
          <Citation citation={analysis.summary.citation} />
        </div>
      ) : null}

      <div className="card" data-testid="analysis-anomalies">
        <h4>Anomaly flags</h4>
        {analysis.anomalies.length === 0 ? (
          <div className="muted" data-testid="no-anomalies">
            No anomalies flagged.
          </div>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none' }}>
            {analysis.anomalies.map((a) => (
              <li
                key={a.code}
                className="card anomaly-flag"
                data-testid={`anomaly-${a.code}`}
                style={{ marginTop: 8 }}
              >
                <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                  <span
                    className="status-chip rejected"
                    data-testid="anomaly-severity"
                    data-severity={a.severity}
                  >
                    {a.severity}
                  </span>
                  <strong>{a.message}</strong>
                </div>
                <div className="card-sub" data-testid="anomaly-confidence">
                  Confidence {pct(a.confidence)} · {a.rationale}
                </div>
                {a.cross_references.length ? (
                  <div className="card-sub" data-testid="anomaly-cross-refs">
                    Cross-checked against: {a.cross_references.join(', ')}
                  </div>
                ) : null}
                <Citation citation={a.citation} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card" data-testid="analysis-drafts">
        <h4>AI-drafted values (require explicit opt-in)</h4>
        {changes.length === 0 ? (
          <div className="muted" data-testid="no-drafts">
            No drafted values.
          </div>
        ) : (
          <table className="table diff-table" data-testid="diff-table">
            <thead>
              <tr>
                <th>Accept</th>
                <th>Field</th>
                <th>Current</th>
                <th>Proposed</th>
                <th>Provenance</th>
                <th>Confidence</th>
                <th>Rationale &amp; citation</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => {
                // The opt-in reflects either an already-accepted change or the
                // human's local selection; it DEFAULTS TO UNCHECKED.
                const checked = change.accepted || acceptedFields[change.field_path] === true;
                return (
                  <tr
                    key={change.change_id}
                    className={`ai-suggested${checked ? ' opted-in' : ''}`}
                    data-testid={`ai-change-${change.field_path}`}
                    data-ai-suggested={change.ai_suggested}
                    data-accepted={checked}
                  >
                    <td>
                      <input
                        type="checkbox"
                        data-testid={`accept-${change.field_path}`}
                        aria-label={`Accept AI-suggested value for ${change.field_path}`}
                        checked={checked}
                        onChange={(e) => onAcceptChange?.(change, e.target.checked)}
                      />
                    </td>
                    <td>{change.field_path}</td>
                    <td>{display(change.current_value)}</td>
                    <td>
                      <span
                        className="status-chip"
                        data-testid="ai-badge"
                        title="Value drafted by AI — decision support only."
                        style={{ marginRight: 6 }}
                      >
                        AI suggested
                      </span>
                      {display(change.proposed_value)}
                    </td>
                    <td>
                      <ProvenanceBadge provenance={change.provenance} />
                    </td>
                    <td data-testid="change-confidence">
                      {change.ai_confidence === null ? '—' : pct(change.ai_confidence)}
                    </td>
                    <td>
                      <div>{change.ai_rationale ?? '—'}</div>
                      {change.citation ? <Citation citation={change.citation} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
