import { useTranslation } from 'react-i18next';
import type { HealthContribution } from '../api/types';
import { fmtNumber } from '../lib/format';

interface Props {
  contributions: HealthContribution[];
}

/**
 * Visualizes how each factor pushes a health score up or down. Negative deltas
 * (penalties) render in warning/danger colors extending left; positive deltas
 * render green extending right, around a shared center baseline.
 */
export function ContributionBreakdown({ contributions }: Props) {
  const { t } = useTranslation();
  if (!contributions.length) {
    return <div className="empty">{t('contribution.empty')}</div>;
  }
  const maxAbs = Math.max(...contributions.map((c) => Math.abs(c.delta)), 1);

  return (
    <div data-testid="contribution-breakdown">
      {contributions.map((c) => {
        const negative = c.delta < 0;
        const widthPct = (Math.abs(c.delta) / maxAbs) * 50;
        const color = negative
          ? c.delta <= -6
            ? 'var(--delta-adverse-strong)'
            : 'var(--delta-adverse)'
          : 'var(--delta-favourable)';
        return (
          <div className="contrib-row" key={c.factor}>
            <div>
              <div className="factor">{c.factor}</div>
              <div className="detail">{c.detail}</div>
            </div>
            <div className="contrib-bar">
              <div
                className="seg"
                style={{
                  background: color,
                  left: negative ? `${50 - widthPct}%` : '50%',
                  width: `${widthPct}%`,
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: '50%',
                  top: -2,
                  bottom: -2,
                  width: 1,
                  background: 'var(--border)',
                }}
              />
            </div>
            <div className="contrib-value" style={{ color }}>
              {c.delta > 0 ? '+' : ''}
              {fmtNumber(c.delta, 1)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
