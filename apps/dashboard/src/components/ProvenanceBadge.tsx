import type { DataProvenance } from '../api/types';
import { provenanceMeta } from '../lib/format';

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
  const meta = provenanceMeta[provenance];
  const state = meta.validated ? 'validated' : 'unvalidated';
  return (
    <span
      className={`prov-badge ${state}${className ? ` ${className}` : ''}`}
      title={meta.title}
      data-testid="provenance-badge"
      data-provenance={provenance}
    >
      {meta.label}
    </span>
  );
}
