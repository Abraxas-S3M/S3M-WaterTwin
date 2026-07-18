import { useTranslation } from 'react-i18next';
import type { DataProvenance, HealthBand } from '../api/types';
import { bandColor, fmtNumber } from '../lib/format';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  score: number;
  band: HealthBand;
  provenance?: DataProvenance;
  compact?: boolean;
}

export function HealthBar({ score, band, provenance, compact }: Props) {
  const { t } = useTranslation();
  const color = bandColor[band];
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div className="health-bar" data-testid="health-bar">
      <div className="track">
        <div className="fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      {!compact && (
        <div className="meta">
          <span
            className="band-chip"
            style={{
              // A ~13% tint of the band colour. Previously the hex was
              // concatenated as `${color}22` (an #RRGGBBAA suffix); now that the
              // band colour is a `var()` token, that string concat is invalid, so
              // the same 0x22 alpha (34/255) is applied via color-mix instead.
              background: `color-mix(in srgb, ${color} calc(34 / 255 * 100%), transparent)`,
              color,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: color,
                display: 'inline-block',
              }}
            />
            {band}
          </span>
          <span className="row" style={{ gap: 8 }}>
            <strong style={{ color }}>{fmtNumber(score, 1)}</strong>
            <span className="muted">{t('healthBar.outOf100')}</span>
            {provenance ? <ProvenanceBadge provenance={provenance} /> : null}
          </span>
        </div>
      )}
    </div>
  );
}
