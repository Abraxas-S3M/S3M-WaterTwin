import type { DataProvenance, HealthBand } from '../api/types';

export function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function fmtTime(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export const bandColor: Record<HealthBand, string> = {
  Healthy: '#2ecc71',
  Monitor: '#a3e635',
  Degraded: '#f1c40f',
  HighRisk: '#e67e22',
  Critical: '#e74c3c',
};

// Whether each provenance represents validated/measured data. Human-readable
// labels and tooltips are localized (see the `provenance.*` locale keys).
export const provenanceValidated: Record<DataProvenance, boolean> = {
  measured: true,
  synthetic: false,
  simulated: false,
  preliminary: false,
  estimated: false,
};

export function fmtMoney(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `$${fmtNumber(value, digits)}`;
}

export function riskColor(band: string): string {
  switch (band) {
    case 'low':
      return '#2ecc71';
    case 'elevated':
      return '#f1c40f';
    case 'high':
      return '#e74c3c';
    default:
      return '#8b95a5';
  }
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
