import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { IngestClass, IngestClassification, IngestScope } from '../../api/types';

interface FacilityOption {
  id: string;
  name: string;
}

interface EntityOption {
  id: string;
  label: string;
}

interface Props {
  classification: IngestClassification;
  facilities: FacilityOption[];
  entities: EntityOption[];
  initialScope?: IngestScope | null;
  onConfirm: (confirmedClass: IngestClass, scope: IngestScope) => void;
}

/**
 * Step 2 — Classify. Presents the server's sniffed classification as a
 * SUGGESTION the user must confirm or correct, with facility and asset-scope
 * pickers. The confirm button is the only way forward.
 */
export function ClassifyStep({
  classification,
  facilities,
  entities,
  initialScope,
  onConfirm,
}: Props) {
  const { t } = useTranslation();
  const [chosenClass, setChosenClass] = useState<IngestClass>(
    classification.suggested_class,
  );
  const [facilityId, setFacilityId] = useState<string>(
    initialScope?.facility_id ?? facilities[0]?.id ?? '',
  );
  const [entity, setEntity] = useState<string>(initialScope?.entity ?? '');

  const confidencePct = Math.round(classification.confidence * 100);

  return (
    <div className="stack" data-testid="ingest-classify-step">
      <div className="card" data-testid="ingest-suggestion">
        <h3>{t('dataIntake.classify.suggestionTitle')}</h3>
        <p className="context">
          {t('dataIntake.classify.suggestionHint', {
            confidence: confidencePct,
          })}
        </p>
        <p>
          <span className="status-chip approved" data-testid="ingest-suggested-class">
            {t(`dataIntake.classes.${classification.suggested_class}`)}
          </span>{' '}
          <span className="muted">{classification.detail}</span>
        </p>

        <label className="stack" htmlFor="ingest-class-select">
          <span>{t('dataIntake.classify.confirmClassLabel')}</span>
          <select
            id="ingest-class-select"
            data-testid="ingest-class-select"
            value={chosenClass}
            onChange={(e) => setChosenClass(e.target.value as IngestClass)}
          >
            {classification.supported_classes.map((c) => (
              <option key={c} value={c}>
                {t(`dataIntake.classes.${c}`)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="card" data-testid="ingest-scope">
        <h3>{t('dataIntake.classify.scopeTitle')}</h3>
        <label className="stack" htmlFor="ingest-facility-select">
          <span>{t('dataIntake.classify.facilityLabel')}</span>
          <select
            id="ingest-facility-select"
            data-testid="ingest-facility-select"
            value={facilityId}
            onChange={(e) => setFacilityId(e.target.value)}
          >
            {facilities.length === 0 ? (
              <option value="">{t('dataIntake.classify.noFacility')}</option>
            ) : null}
            {facilities.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>

        <label className="stack" htmlFor="ingest-entity-select">
          <span>{t('dataIntake.classify.entityLabel')}</span>
          <select
            id="ingest-entity-select"
            data-testid="ingest-entity-select"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
          >
            <option value="">{t('dataIntake.classify.allEntities')}</option>
            {entities.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn primary"
          data-testid="ingest-confirm-class"
          onClick={() =>
            onConfirm(chosenClass, {
              facility_id: facilityId || null,
              entity: entity || null,
            })
          }
        >
          {t('dataIntake.classify.confirm')}
        </button>
      </div>
    </div>
  );
}
