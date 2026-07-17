import type { ReactNode } from 'react';
import type { DataProvenance } from '../api/types';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  provenance?: DataProvenance;
  footer?: ReactNode;
  accent?: string;
}

export function KpiCard({ label, value, unit, provenance, footer, accent }: Props) {
  return (
    <div className="card kpi" data-testid="kpi-card">
      <div className="kpi-label">
        <span>{label}</span>
        {provenance ? <ProvenanceBadge provenance={provenance} /> : null}
      </div>
      <div className="kpi-value" style={accent ? { color: accent } : undefined}>
        {value}
        {unit ? <span className="unit">{unit}</span> : null}
      </div>
      {footer ? <div className="kpi-foot">{footer}</div> : null}
    </div>
  );
}
