import { useState } from 'react';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import {
  useCaptureTrainingAction,
  useStartTrainingSession,
  useSubmitTrainingSession,
  useTrainingRecords,
  useTrainingScenarios,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, fmtTime, titleCase } from '../lib/format';
import type {
  TrainingRecord,
  TrainingScenario,
  TrainingSession,
} from '../api/types';

const ACTION_KINDS = ['diagnosis', 'action', 'approval', 'note'] as const;

function bandColor(band: string): string {
  switch (band) {
    case 'Exemplary':
      return 'var(--ok)';
    case 'Proficient':
      return 'var(--grade-proficient)';
    case 'Developing':
      return 'var(--warn)';
    default:
      return 'var(--danger)';
  }
}

export function TrainingSimulator() {
  const operator = useDashboardStore((s) => s.operatorName);
  const scenarios = useTrainingScenarios();
  const records = useTrainingRecords();

  const startSession = useStartTrainingSession();
  const captureAction = useCaptureTrainingAction();
  const submitSession = useSubmitTrainingSession();

  const [session, setSession] = useState<TrainingSession | null>(null);
  const [record, setRecord] = useState<TrainingRecord | null>(null);
  const [actionKind, setActionKind] = useState<string>('diagnosis');
  const [actionText, setActionText] = useState<string>('');
  const [rubricKey, setRubricKey] = useState<string>('');

  const beginDrill = (scenario: TrainingScenario) => {
    setRecord(null);
    startSession.mutate(
      { scenarioId: scenario.scenario_id, operator },
      { onSuccess: (res) => setSession(res.session) },
    );
  };

  const submitAction = () => {
    if (!session || actionText.trim().length === 0) return;
    captureAction.mutate(
      {
        sessionId: session.session_id,
        body: {
          kind: actionKind,
          text: actionText.trim(),
          rubric_key: rubricKey || null,
          approved: actionKind === 'approval' ? true : null,
        },
      },
      {
        onSuccess: (res) => {
          setSession(res.session);
          setActionText('');
          setRubricKey('');
        },
      },
    );
  };

  const scoreDrill = () => {
    if (!session) return;
    submitSession.mutate(session.session_id, {
      onSuccess: (res) => setRecord(res.record),
    });
  };

  const resetDrill = () => {
    setSession(null);
    setRecord(null);
    setActionText('');
    setRubricKey('');
  };

  const observed = session?.twin_summary?.observed ?? {};

  return (
    <div className="stack" data-testid="training-simulator">
      <div className="page-header">
        <div>
          <h2>Operator Training Simulator</h2>
          <div className="context">
            Guided fault drills on the digital twin. Inject a scenario, diagnose it, capture your
            actions &amp; approvals, and score against an expected-response rubric.
          </div>
        </div>
        <ProvenanceBadge provenance="simulated" />
      </div>

      <div
        className="safety-banner error"
        role="status"
        aria-live="polite"
        data-testid="training-disclaimer"
      >
        <span className="badge-lock">TRAINING · SIMULATION</span>
        <span>
          Sandboxed rehearsal only. This simulator <strong>cannot emit any command</strong> — no
          real control action is taken and nothing reaches any plant, OT, PLC or SCADA system.
          Scores are training feedback, not a validated assessment.
        </span>
      </div>

      {!session ? (
        <>
          <div className="card" data-testid="scenario-catalog">
            <h3>Available Drills</h3>
            {scenarios.isLoading ? (
              <div className="spinner">Loading drills…</div>
            ) : scenarios.isError || !scenarios.data ? (
              <div className="muted">
                {(scenarios.error as Error)?.message ?? 'Could not load training drills.'}
              </div>
            ) : (
              <div className="grid cols-2">
                {scenarios.data.scenarios.map((scenario) => (
                  <div
                    key={scenario.scenario_id}
                    className="card"
                    data-testid={`scenario-${scenario.scenario_id}`}
                  >
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <h4 style={{ margin: 0 }}>{scenario.title}</h4>
                      <span className="phase-tag">{scenario.difficulty}</span>
                    </div>
                    <div className="muted" style={{ margin: '4px 0' }}>
                      {scenario.category}
                    </div>
                    <p>{scenario.briefing}</p>
                    <button
                      className="btn primary"
                      data-testid={`start-drill-${scenario.scenario_id}`}
                      disabled={startSession.isPending}
                      onClick={() => beginDrill(scenario)}
                    >
                      {startSession.isPending ? 'Injecting…' : 'Start drill'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" data-testid="training-records">
            <h3>
              Training Records
              <ProvenanceBadge provenance="simulated" className="prov-inline" />
            </h3>
            {records.data && records.data.records.length > 0 ? (
              <table className="data">
                <thead>
                  <tr>
                    <th>Completed</th>
                    <th>Drill</th>
                    <th>Operator</th>
                    <th className="cell-num">Score</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {records.data.records.map((r) => (
                    <tr key={r.record_id} data-testid={`record-${r.record_id}`}>
                      <td>{fmtTime(r.completed_at)}</td>
                      <td>{r.scenario_title}</td>
                      <td className="muted">{r.operator}</td>
                      <td className="cell-num">
                        <strong>{fmtNumber(r.score.percentage, 0)}%</strong>
                      </td>
                      <td>
                        <span className={`status-chip ${r.score.passed ? 'approved' : 'rejected'}`}>
                          {r.score.band}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty">No training records yet. Complete a drill to create one.</div>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="card" data-testid="training-twin">
            <div className="row row-split">
              <h3>
                {session.scenario.title}
                <ProvenanceBadge provenance="simulated" className="prov-inline" />
              </h3>
              <button className="btn ghost" data-testid="exit-drill" onClick={resetDrill}>
                Exit drill
              </button>
            </div>
            <p className="muted">{session.twin_summary.headline}</p>
            <p className="muted" style={{ fontSize: '0.85em' }}>
              Injected from: {session.scenario.derived_from}
            </p>
            <div className="grid kpis">
              {Object.entries(observed).map(([metric, value]) => (
                <KpiCard
                  key={metric}
                  label={titleCase(metric)}
                  value={typeof value === 'number' ? fmtNumber(value, 2) : String(value)}
                  provenance="simulated"
                />
              ))}
            </div>
            {session.injected_telemetry.length > 0 ? (
              <table className="data" data-testid="injected-telemetry">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Metric</th>
                    <th className="cell-num">Value</th>
                    <th>Unit</th>
                    <th>Provenance</th>
                  </tr>
                </thead>
                <tbody>
                  {session.injected_telemetry.map((t, i) => (
                    <tr key={`${t.asset_id}-${t.metric}-${i}`}>
                      <td>{t.asset_id}</td>
                      <td>{titleCase(t.metric)}</td>
                      <td className="cell-num">{fmtNumber(t.value, 2)}</td>
                      <td className="muted">{t.unit}</td>
                      <td>
                        <ProvenanceBadge provenance={t.provenance} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>

          <div className="grid cols-2">
            <div className="card" data-testid="rubric-guidance">
              <h3>Expected Response</h3>
              <p className="muted">
                Address each objective below through your captured actions. The exact scoring keys
                stay hidden — respond in your own words.
              </p>
              <ul>
                {session.scenario.rubric.map((item) => (
                  <li key={item.key}>
                    <strong>{item.prompt}</strong>
                    <div className="muted">{item.guidance}</div>
                  </li>
                ))}
              </ul>
            </div>

            <div className="card" data-testid="action-capture">
              <h3>Capture Action / Approval</h3>
              <div className="stack">
                <label>
                  <span className="muted">Type</span>
                  <select
                    data-testid="action-kind"
                    value={actionKind}
                    onChange={(e) => setActionKind(e.target.value)}
                  >
                    {ACTION_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {titleCase(k)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="muted">Objective (optional)</span>
                  <select
                    data-testid="action-rubric-key"
                    value={rubricKey}
                    onChange={(e) => setRubricKey(e.target.value)}
                  >
                    <option value="">— none —</option>
                    {session.scenario.rubric.map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.prompt}
                      </option>
                    ))}
                  </select>
                </label>
                <textarea
                  data-testid="training-action-text"
                  placeholder="Describe your diagnosis, action or approval…"
                  value={actionText}
                  onChange={(e) => setActionText(e.target.value)}
                  rows={3}
                />
                <div className="btn-row">
                  <button
                    className="btn"
                    data-testid="capture-action"
                    disabled={captureAction.isPending || actionText.trim().length === 0}
                    onClick={submitAction}
                  >
                    {captureAction.isPending ? 'Capturing…' : 'Capture action'}
                  </button>
                  <button
                    className="btn primary"
                    data-testid="submit-drill"
                    disabled={submitSession.isPending || session.actions.length === 0}
                    onClick={scoreDrill}
                  >
                    {submitSession.isPending ? 'Scoring…' : 'Submit & score'}
                  </button>
                </div>
              </div>

              {session.actions.length > 0 ? (
                <table className="data" data-testid="captured-actions">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Action</th>
                      <th>Sandboxed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.actions.map((a) => (
                      <tr key={a.action_id}>
                        <td className="muted">{titleCase(a.kind)}</td>
                        <td>{a.text}</td>
                        <td>
                          <span className="status-chip approved">
                            {a.emitted_command ? 'command!' : 'no command'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty">No actions captured yet.</div>
              )}
            </div>
          </div>

          {record ? (
            <div className="card" data-testid="training-score">
              <div className="row row-split">
                <h3>
                  Training Record
                  <ProvenanceBadge provenance="simulated" className="prov-inline" />
                </h3>
                <button className="btn primary" data-testid="new-drill" onClick={resetDrill}>
                  Start another drill
                </button>
              </div>
              <div className="grid kpis">
                <KpiCard
                  label="Score"
                  value={fmtNumber(record.score.percentage, 0)}
                  unit="%"
                  accent={bandColor(record.score.band)}
                  footer={record.score.band}
                />
                <KpiCard
                  label="Result"
                  value={record.score.passed ? 'Passed' : 'Needs review'}
                  accent={record.score.passed ? 'var(--ok)' : 'var(--danger)'}
                />
                <KpiCard
                  label="Points"
                  value={`${fmtNumber(record.score.total_score, 1)} / ${fmtNumber(
                    record.score.max_score,
                    1,
                  )}`}
                />
              </div>
              <table className="data">
                <thead>
                  <tr>
                    <th>Objective</th>
                    <th>Met</th>
                    <th>Feedback</th>
                  </tr>
                </thead>
                <tbody>
                  {record.score.items.map((item) => (
                    <tr key={item.key} data-testid={`score-item-${item.key}`}>
                      <td>{item.prompt}</td>
                      <td>
                        <span className={`status-chip ${item.matched ? 'approved' : 'rejected'}`}>
                          {item.matched ? 'yes' : 'no'}
                        </span>
                      </td>
                      <td className="muted">{item.feedback}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
