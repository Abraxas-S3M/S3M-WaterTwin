import { useEffect, useState } from 'react';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import {
  useCmmsStatus,
  useMaintenanceRecommendations,
  useWorkOrderDecision,
  useWorkOrders,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { useCapabilities } from '../auth/useAuth';
import { fmtMoney, fmtNumber, fmtTime } from '../lib/format';
import type {
  MaintenanceWorkOrder,
  RecommendationCard as RecCard,
  WorkOrderPriority,
} from '../api/types';

const priorityClass: Record<WorkOrderPriority, string> = {
  low: 'low',
  medium: 'elevated',
  high: 'high',
  urgent: 'high',
};

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${fmtNumber(value * 100, 0)}%`;
}

/**
 * Maintenance Center.
 *
 * Surfaces the traceable flow:
 *   PdM alert → proposed work order → operator approval → audit entry.
 *
 * Every work order is DERIVED from a predictive-maintenance alert and carries
 * the originating model + evidence. Approval is an advisory operator action; a
 * work order is a CMMS ticket proposal, never a control/OT command.
 */
export function MaintenanceCenter() {
  const operator = useDashboardStore((s) => s.operatorName);
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);
  const { approve: canDecide } = useCapabilities();

  const workOrders = useWorkOrders();
  const recommendations = useMaintenanceRecommendations();
  const cmms = useCmmsStatus();
  const decision = useWorkOrderDecision();

  const orders = workOrders.data?.work_orders ?? [];
  const cards = recommendations.data?.cards ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (selectedId === null && orders.length > 0) {
      setSelectedId(orders[0].work_order_id);
    }
  }, [orders, selectedId]);

  const selected: MaintenanceWorkOrder | undefined = orders.find(
    (w) => w.work_order_id === selectedId,
  );
  const sourceCard: RecCard | undefined = cards.find(
    (c) => c.recommendation_id === selected?.source_recommendation_id,
  );

  const handleDecision = (id: string, status: 'approved' | 'rejected') =>
    decision.mutate({ id, body: { status, actor: operator } });

  const cmmsDesc = cmms.data?.cmms;

  return (
    <div className="stack" data-testid="maintenance-center">
      <div className="page-header">
        <div>
          <h2>Maintenance Center</h2>
          <div className="context">
            Work orders derived from predictive-maintenance alerts · advisory only
            <ProvenanceBadge provenance="preliminary" />
          </div>
        </div>
        {cmmsDesc ? (
          <div className="context" data-testid="cmms-status">
            CMMS: <strong>{cmmsDesc.name}</strong>{' '}
            <span className={`status-chip ${cmmsDesc.read_only ? 'pending' : 'approved'}`}>
              {cmmsDesc.read_only ? 'read-only' : 'write-back enabled'}
            </span>
          </div>
        ) : null}
      </div>

      <div className="card">
        <p className="muted">
          Each work order is <strong>traceable</strong> to the predictive-maintenance model and
          evidence it came from. Approving a work order is an advisory operator decision recorded
          in the audit trail — a work order is a <strong>CMMS ticket</strong>, never a device
          command. No control write is ever issued.
        </p>

        {workOrders.isLoading ? (
          <div className="spinner">Loading work orders…</div>
        ) : orders.length === 0 ? (
          <div className="empty">No proposed work orders.</div>
        ) : (
          <table className="data" data-testid="work-order-table">
            <thead>
              <tr>
                <th>Work order</th>
                <th>Asset</th>
                <th>Source alert</th>
                <th>Priority</th>
                <th className="cell-num">Fail prob (30d)</th>
                <th className="cell-num">RUL (d)</th>
                <th>Status</th>
                <th>CMMS</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((w) => (
                <tr
                  key={w.work_order_id}
                  className={`clickable${selectedId === w.work_order_id ? ' active' : ''}`}
                  data-testid={`work-order-row-${w.work_order_id}`}
                  onClick={() => setSelectedId(w.work_order_id)}
                >
                  <td>{w.work_order_id}</td>
                  <td>{w.asset_name ?? w.asset_id}</td>
                  <td className="muted">{w.source_alert_code ?? '—'}</td>
                  <td>
                    <span className={`status-chip ${priorityClass[w.priority]}`}>
                      {w.priority}
                    </span>
                  </td>
                  <td className="cell-num">{fmtPct(w.failure_probability_30d)}</td>
                  <td className="cell-num">{fmtNumber(w.rul_days ?? undefined, 0)}</td>
                  <td>
                    <span className={`status-chip ${w.approval_status}`}>{w.status}</span>
                  </td>
                  <td className="muted">
                    {w.cmms_sync_status === 'synced' ? w.cmms_external_id : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected ? (
        <div className="card" data-testid="work-order-detail">
          <div className="row row-split">
            <h3>{selected.title}</h3>
            <button className="btn" onClick={() => openAssetTwin(selected.asset_id)}>
              Open Asset Twin
            </button>
          </div>

          {/* Traceability flow: alert -> work order -> approval -> audit */}
          <ol className="flow-steps" data-testid="traceability-flow">
            <li>
              <strong>1 · PdM alert</strong>
              <div className="muted">
                {selected.originating_model ?? 'predictive-maintenance'} ·{' '}
                {selected.source_alert_code ?? '—'} (
                {selected.source_recommendation_id ?? 'n/a'})
              </div>
            </li>
            <li>
              <strong>2 · Proposed work order</strong>
              <div className="muted">{selected.work_order_id}</div>
            </li>
            <li>
              <strong>3 · Operator approval</strong>
              <div className="muted">
                <span className={`status-chip ${selected.approval_status}`}>
                  {selected.approval_status}
                </span>
                {selected.approved_by ? ` by ${selected.approved_by}` : ''}
              </div>
            </li>
            <li>
              <strong>4 · Audit entry</strong>
              <div className="muted">
                {selected.decided_at
                  ? `Recorded ${fmtTime(selected.decided_at)}`
                  : 'Recorded on decision (tamper-evident audit trail)'}
              </div>
            </li>
          </ol>

          <dl className="definition">
            <dt>Description</dt>
            <dd>{selected.description}</dd>
            <dt>Predicted failure mode</dt>
            <dd>{selected.predicted_failure_mode ?? '—'}</dd>
            <dt>Failure probability (30d)</dt>
            <dd>
              {fmtPct(selected.failure_probability_30d)}{' '}
              <ProvenanceBadge provenance="preliminary" />
            </dd>
            <dt>Recommended window</dt>
            <dd>{selected.recommended_window ?? '—'}</dd>
            <dt>Spares required</dt>
            <dd>{selected.spares_required.length ? selected.spares_required.join(', ') : 'None'}</dd>
            <dt>Estimated downtime</dt>
            <dd>{fmtNumber(selected.estimated_downtime_hours ?? undefined, 0)} h</dd>
            <dt>Estimated cost</dt>
            <dd>{fmtMoney(selected.estimated_cost)} (preliminary)</dd>
            <dt>CMMS ticket</dt>
            <dd>
              {selected.cmms_sync_status === 'synced'
                ? `${selected.cmms_external_id} (${selected.cmms_system})`
                : 'Not written back (a ticket, never a control command)'}
            </dd>
          </dl>

          {selected.ranked_causes.length ? (
            <div>
              <div className="card-sub" style={{ marginBottom: 4 }}>
                Evidence — ranked probable causes (from the PdM model)
              </div>
              <ol className="causes">
                {selected.ranked_causes.map((c) => (
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
          ) : null}

          {sourceCard ? (
            <details>
              <summary className="card-sub">Originating PdM recommendation</summary>
              <div className="muted" style={{ marginTop: 6 }}>
                {sourceCard.recommendation_id}: {sourceCard.summary}
              </div>
            </details>
          ) : null}

          {canDecide ? (
            <div className="btn-row">
              <button
                className="btn approve"
                disabled={decision.isPending || selected.approval_status !== 'pending'}
                onClick={() => handleDecision(selected.work_order_id, 'approved')}
                data-testid="approve-work-order"
              >
                Approve
              </button>
              <button
                className="btn reject"
                disabled={decision.isPending || selected.approval_status !== 'pending'}
                onClick={() => handleDecision(selected.work_order_id, 'rejected')}
                data-testid="reject-work-order"
              >
                Reject
              </button>
              {selected.approval_status !== 'pending' ? (
                <span className="muted" style={{ alignSelf: 'center' }}>
                  Decision recorded — advisory only, no control write is issued.
                </span>
              ) : null}
            </div>
          ) : (
            <div className="btn-row" data-testid="approve-role-gate">
              <span className="muted">
                Approving or rejecting a work order requires the <strong>operator</strong> role.
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="empty">Select a work order to see its traceability and approval.</div>
        </div>
      )}
    </div>
  );
}
