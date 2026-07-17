import { useState } from 'react';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { RecommendationCard } from '../components/RecommendationCard';
import { useAskAssistant, useAssistantExamples, useDecision } from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, fmtTime } from '../lib/format';
import type { AssistantResponse } from '../api/types';

function EngineStatusBadge({ status }: { status: string }) {
  const local = status === 'fallback_local';
  return (
    <span
      className={`status-chip ${local ? 'rejected' : 'approved'}`}
      data-testid="engine-status"
      data-engine-status={status}
      title={
        local
          ? 'S3M-Core quad-engine unreachable — grounded local fallback used.'
          : 'Answer orchestrated by the S3M-Core quad-engine.'
      }
    >
      {local ? 'Local fallback' : 'Quad-engine'}
    </span>
  );
}

function EvidenceBlock({ response }: { response: AssistantResponse }) {
  const ev = response.evidence;
  return (
    <div className="card" data-testid="assistant-evidence">
      <h3>
        Evidence
        <ProvenanceBadge provenance={response.provenance} className="prov-inline" />
      </h3>
      <div className="grid kpis">
        <div className="kpi-mini" data-testid="evidence-data-timestamp">
          <div className="card-sub">Data timestamp</div>
          <div>{fmtTime(ev.data_timestamp)}</div>
        </div>
        <div className="kpi-mini" data-testid="evidence-confidence">
          <div className="card-sub">Confidence</div>
          <div>
            <strong style={{ color: 'var(--accent)' }}>
              {fmtNumber(response.confidence * 100, 0)}%
            </strong>
          </div>
        </div>
        <div className="kpi-mini">
          <div className="card-sub">Source engine</div>
          <div>
            <EngineStatusBadge status={response.source_engine_status} />
          </div>
        </div>
      </div>

      <div className="row" style={{ gap: 24, flexWrap: 'wrap', marginTop: 8 }}>
        <div data-testid="evidence-assets">
          <div className="card-sub">Assets reviewed</div>
          {ev.assets_reviewed.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.assets_reviewed.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">none</div>
          )}
        </div>
        <div data-testid="evidence-documents">
          <div className="card-sub">Documents reviewed</div>
          {ev.documents_reviewed.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.documents_reviewed.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">none</div>
          )}
        </div>
        <div data-testid="evidence-simulations">
          <div className="card-sub">Simulations used</div>
          {ev.simulation_ids.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.simulation_ids.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">none</div>
          )}
        </div>
      </div>

      <div data-testid="evidence-assumptions" style={{ marginTop: 8 }}>
        <div className="card-sub">Assumptions</div>
        <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {ev.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function OperationsAssistant() {
  const examples = useAssistantExamples();
  const ask = useAskAssistant();
  const decision = useDecision();
  const operator = useDashboardStore((s) => s.operatorName);
  const [question, setQuestion] = useState('');

  const response = ask.data;

  const submit = (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuestion(text);
    ask.mutate({ question: text, requestedBy: operator });
  };

  const handleDecision = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  return (
    <div className="stack" data-testid="operations-assistant">
      <div className="page-header">
        <div>
          <h2>Operations Assistant</h2>
          <div className="context">
            Ask about anything the platform computes. Every answer is{' '}
            <strong>grounded</strong> in platform data + retrieved documents (never general model
            knowledge) and shows exactly what was used. Advisory / read-only — any recommended
            action requires operator approval; no control write is issued.
          </div>
        </div>
        <ProvenanceBadge provenance="preliminary" />
      </div>

      <div className="card">
        <form
          className="row"
          style={{ gap: 8, alignItems: 'stretch' }}
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
        >
          <input
            className="input"
            style={{ flex: 1 }}
            data-testid="assistant-question"
            placeholder="e.g. Why is HPP-001 degrading?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label="Question"
          />
          <button
            className="btn"
            type="submit"
            data-testid="assistant-ask"
            disabled={ask.isPending || !question.trim()}
          >
            {ask.isPending ? 'Asking…' : 'Ask'}
          </button>
        </form>
        <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          {(examples.data?.examples ?? []).map((ex) => (
            <button
              key={ex.intent}
              type="button"
              className="chip"
              data-testid={`example-${ex.intent}`}
              onClick={() => submit(ex.question)}
            >
              {ex.question}
            </button>
          ))}
        </div>
      </div>

      {ask.isError ? (
        <div className="card error" data-testid="assistant-error">
          Could not reach the assistant. Please try again.
        </div>
      ) : null}

      {response ? (
        <>
          <div className="card" data-testid="assistant-answer">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>Answer</h3>
              <div className="row" style={{ gap: 6 }}>
                <span className="status-chip" data-testid="assistant-intent">
                  {response.intent}
                </span>
                <EngineStatusBadge status={response.source_engine_status} />
              </div>
            </div>
            <p style={{ whiteSpace: 'pre-wrap' }}>{response.answer}</p>
            <div className="card-sub">
              Read-only advisory answer — grounded in platform data + documents, not general model
              knowledge.
            </div>
          </div>

          <EvidenceBlock response={response} />

          {response.recommended_action ? (
            <div className="card" data-testid="assistant-recommendation">
              <h3>Recommended Action</h3>
              <RecommendationCard
                rec={response.recommended_action}
                busy={decision.isPending}
                onApprove={(id) => handleDecision(id, 'approve')}
                onReject={(id) => handleDecision(id, 'reject')}
              />
            </div>
          ) : null}
        </>
      ) : (
        <div className="card empty" data-testid="assistant-empty">
          Ask a question or pick an example prompt to get a grounded, evidence-backed answer.
        </div>
      )}
    </div>
  );
}
