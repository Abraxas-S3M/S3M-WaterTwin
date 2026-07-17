import type { RecommendationCard as RecCard } from '../api/types';
import { fmtNumber, fmtTime } from '../lib/format';
import { useCapabilities } from '../auth/useAuth';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  rec: RecCard;
  onApprove?: (recId: string) => void;
  onReject?: (recId: string) => void;
  busy?: boolean;
}

export function RecommendationCard({ rec, onApprove, onReject, busy }: Props) {
  const decided = rec.approval_status !== 'pending';
  const { approve: canDecide } = useCapabilities();
  const hasHandlers = Boolean(onApprove || onReject);
  return (
    <div className="rec-card" data-testid="recommendation-card">
      <div className="rec-top">
        <div>
          <div className="rec-summary">{rec.summary}</div>
          <div className="card-sub">
            {rec.recommendation_id} · {fmtTime(rec.created_at)}
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <span className={`status-chip ${rec.approval_status}`}>{rec.approval_status}</span>
          <ProvenanceBadge
            provenance={rec.source_engine_status === 'preliminary' ? 'preliminary' : 'simulated'}
          />
        </div>
      </div>

      <div className="row" style={{ gap: 16 }}>
        <span className="card-sub">
          Confidence: <strong style={{ color: 'var(--accent)' }}>{fmtNumber(rec.confidence * 100, 0)}%</strong>
        </span>
        {rec.asset_id ? <span className="card-sub">Asset: {rec.asset_id}</span> : null}
        <span className="card-sub">Mode: {rec.control_boundary.control_mode}</span>
      </div>

      <div>
        <div className="card-sub" style={{ marginBottom: 4 }}>Ranked probable causes</div>
        <ol className="causes">
          {rec.ranked_causes.map((c) => (
            <li key={c.cause}>
              <div className="cause-line">
                <span>{c.cause}</span>
                <span className="cause-prob">{fmtNumber(c.probability * 100, 0)}%</span>
              </div>
              <div className="cause-evidence">{c.evidence}</div>
            </li>
          ))}
        </ol>
      </div>

      <div className="rec-action">
        <strong>Recommended action:</strong> {rec.recommended_action}
      </div>

      {rec.evidence?.assumptions?.length ? (
        <details>
          <summary className="card-sub">Evidence &amp; assumptions</summary>
          <ul className="card-sub" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            <li>Telemetry window: {rec.evidence.telemetry_window}</li>
            {rec.evidence.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {hasHandlers && canDecide && (
        <div className="btn-row">
          <button
            className="btn approve"
            disabled={busy || decided}
            onClick={() => onApprove?.(rec.recommendation_id)}
            data-testid="approve-button"
          >
            Approve
          </button>
          <button
            className="btn reject"
            disabled={busy || decided}
            onClick={() => onReject?.(rec.recommendation_id)}
            data-testid="reject-button"
          >
            Reject
          </button>
          {decided ? (
            <span className="muted" style={{ alignSelf: 'center' }}>
              Advisory only — no control write is issued.
            </span>
          ) : null}
        </div>
      )}

      {hasHandlers && !canDecide && (
        <div className="btn-row" data-testid="approve-role-gate">
          <span className="muted">
            Approving or rejecting requires the <strong>operator</strong> role.
          </span>
        </div>
      )}
    </div>
  );
}
