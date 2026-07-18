import { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { RecommendationCard } from '../components/RecommendationCard';
import { useAskAssistant, useAssistantExamples, useDecision } from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, fmtTime } from '../lib/format';
import type { AssistantResponse, DocumentProvenance } from '../api/types';

function EngineStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const local = status === 'fallback_local';
  return (
    <span
      className={`status-chip ${local ? 'rejected' : 'approved'}`}
      data-testid="engine-status"
      data-engine-status={status}
      title={local ? t('assistant.engineLocalTitle') : t('assistant.engineQuadTitle')}
    >
      {local ? t('assistant.engineLocal') : t('assistant.engineQuad')}
    </span>
  );
}

function SourceBadge({ provenance }: { provenance: DocumentProvenance }) {
  const { t } = useTranslation();
  const customer = provenance === 'customer_supplied';
  return (
    <span
      className={`status-chip ${customer ? 'elevated' : 'approved'}`}
      data-testid="source-badge"
      data-provenance={provenance}
      title={customer ? t('assistant.sourceCustomerTitle') : t('assistant.sourcePlatformTitle')}
    >
      {customer ? t('assistant.sourceCustomer') : t('assistant.sourcePlatform')}
    </span>
  );
}

function CitationsBlock({ response }: { response: AssistantResponse }) {
  const { t } = useTranslation();
  const citations = response.evidence.citations ?? [];
  if (citations.length === 0) return null;
  return (
    <div data-testid="evidence-citations" style={{ marginTop: 8 }}>
      <div className="card-sub">{t('assistant.citations')}</div>
      <ul className="stack" style={{ margin: '4px 0 0', paddingLeft: 0, listStyle: 'none' }}>
        {citations.map((c) => {
          const provenance: DocumentProvenance = c.provenance ?? 'platform_seeded';
          return (
            <li
              key={c.document_id}
              data-testid="citation"
              data-provenance={provenance}
              className="row"
              style={{ gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}
            >
              <SourceBadge provenance={provenance} />
              <strong>{c.title}</strong>
              <span className="muted">({c.document_id})</span>
              {c.location ? (
                <span className="card-sub" data-testid="citation-location">
                  {t('assistant.location')}: {c.location}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EvidenceBlock({ response }: { response: AssistantResponse }) {
  const { t } = useTranslation();
  const ev = response.evidence;
  return (
    <div className="card" data-testid="assistant-evidence">
      <h3>
        {t('assistant.evidence')}
        <ProvenanceBadge provenance={response.provenance} className="prov-inline" />
      </h3>
      <div className="grid kpis">
        <div className="kpi-mini" data-testid="evidence-data-timestamp">
          <div className="card-sub">{t('assistant.dataTimestamp')}</div>
          <div>{fmtTime(ev.data_timestamp)}</div>
        </div>
        <div className="kpi-mini" data-testid="evidence-confidence">
          <div className="card-sub">{t('assistant.confidence')}</div>
          <div>
            <strong style={{ color: 'var(--accent)' }}>
              {fmtNumber(response.confidence * 100, 0)}%
            </strong>
          </div>
        </div>
        <div className="kpi-mini">
          <div className="card-sub">{t('assistant.sourceEngine')}</div>
          <div>
            <EngineStatusBadge status={response.source_engine_status} />
          </div>
        </div>
      </div>

      <div className="row" style={{ gap: 24, flexWrap: 'wrap', marginTop: 8 }}>
        <div data-testid="evidence-assets">
          <div className="card-sub">{t('assistant.assetsReviewed')}</div>
          {ev.assets_reviewed.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.assets_reviewed.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">{t('common.none')}</div>
          )}
        </div>
        <div data-testid="evidence-documents">
          <div className="card-sub">{t('assistant.documentsReviewed')}</div>
          {ev.documents_reviewed.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.documents_reviewed.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">{t('common.none')}</div>
          )}
        </div>
        <div data-testid="evidence-simulations">
          <div className="card-sub">{t('assistant.simulationsUsed')}</div>
          {ev.simulation_ids.length ? (
            <ul className="card-sub" style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {ev.simulation_ids.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          ) : (
            <div className="muted">{t('common.none')}</div>
          )}
        </div>
      </div>

      <CitationsBlock response={response} />

      <div data-testid="evidence-assumptions" style={{ marginTop: 8 }}>
        <div className="card-sub">{t('assistant.assumptions')}</div>
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
  const { t } = useTranslation();
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
          <h2>{t('assistant.title')}</h2>
          <div className="context">
            <Trans i18nKey="assistant.context">
              Ask about anything the platform computes. Every answer is{' '}
              <strong>grounded</strong> in platform data + retrieved documents (never general model
              knowledge) and shows exactly what was used. Advisory / read-only — any recommended
              action requires operator approval; no control write is issued.
            </Trans>
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
            placeholder={t('assistant.questionPlaceholder')}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label={t('assistant.questionLabel')}
          />
          <button
            className="btn"
            type="submit"
            data-testid="assistant-ask"
            disabled={ask.isPending || !question.trim()}
          >
            {ask.isPending ? t('assistant.asking') : t('assistant.ask')}
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
          {t('assistant.error')}
        </div>
      ) : null}

      {response ? (
        <>
          <div className="card" data-testid="assistant-answer">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <h3>{t('assistant.answer')}</h3>
              <div className="row" style={{ gap: 6 }}>
                <span className="status-chip" data-testid="assistant-intent">
                  {response.intent}
                </span>
                <EngineStatusBadge status={response.source_engine_status} />
              </div>
            </div>
            <p style={{ whiteSpace: 'pre-wrap' }}>{response.answer}</p>
            <div className="card-sub">{t('assistant.answerNote')}</div>
          </div>

          <EvidenceBlock response={response} />

          {response.recommended_action ? (
            <div className="card" data-testid="assistant-recommendation">
              <h3>{t('assistant.recommendedAction')}</h3>
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
          {t('assistant.empty')}
        </div>
      )}
    </div>
  );
}
