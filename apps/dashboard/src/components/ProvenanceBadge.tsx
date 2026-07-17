import { useTranslation } from 'react-i18next';
import type { DataProvenance } from '../api/types';
import { provenanceValidated } from '../lib/format';

interface Props {
  provenance: DataProvenance;
  className?: string;
}

/**
 * Small badge that makes data provenance explicit. Synthetic/simulated/
 * preliminary values are visibly flagged as NOT validated so operators never
 * mistake them for measured, validated readings.
 */
export function ProvenanceBadge({ provenance, className }: Props) {
  const { t } = useTranslation();
  const validated = provenanceValidated[provenance];
  const state = validated ? 'validated' : 'unvalidated';
  return (
    <span
      className={`prov-badge ${state}${className ? ` ${className}` : ''}`}
      title={t(`provenance.${provenance}.title`)}
      data-testid="provenance-badge"
      data-provenance={provenance}
    >
      {t(`provenance.${provenance}.label`)}
    </span>
  );
}
