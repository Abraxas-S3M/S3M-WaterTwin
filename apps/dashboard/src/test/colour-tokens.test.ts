/**
 * Guardrail: no hardcoded colour lives in TypeScript.
 *
 * Every colour the console draws must come from a CSS custom property declared
 * in styles.css, so a theme flip is a values-only change to one file. This suite
 * reads the source as raw text (no parser dependency) and asserts:
 *
 *   - no `.ts`/`.tsx` file under src/ contains a hex colour literal, with a
 *     short, explicit exemption list;
 *   - styles.css declares each migrated token exactly once;
 *   - src/lib/cssVar.ts exists, exports readCssVar, and guards `typeof document`;
 *   - bandColor and riskColor in lib/format.ts return `var(--…)` strings.
 *
 * The two canvas renderers (ECharts in PumpCurve, MapLibre in NetworkTwin)
 * cannot resolve var(); they resolve tokens to concrete values at render time
 * via readCssVar. PumpCurve passes the current hex as each fallback, so those
 * hexes are load-bearing and the file is exempted from the no-hex rule — but we
 * assert separately that every hex in it appears ONLY as a readCssVar fallback.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE =
  typeof import.meta.dirname === 'string'
    ? import.meta.dirname
    : path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, '..');

/** 6-digit (#1a2b3c) and 3-digit (#fff) hex colour literals. */
const HEX = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g;

function read(rel: string): string {
  return readFileSync(path.join(SRC, rel), 'utf8');
}

/** Every `.ts`/`.tsx` file under src/, as paths relative to src/. */
function sourceFiles(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: 'utf8' })
    .map((p) => p.split(path.sep).join('/'))
    .filter((p) => /\.tsx?$/.test(p));
}

/** PumpCurve is the ECharts canvas renderer; its hexes are readCssVar fallbacks. */
const PUMP_CURVE = 'components/PumpCurve.tsx';

/** Exempt: branding build-time defaults, test files, and the PumpCurve fallbacks. */
function isExempt(rel: string): boolean {
  if (rel === 'branding/branding.ts') return true;
  if (rel === PUMP_CURVE) return true;
  if (rel.startsWith('test/') || /\.test\.tsx?$/.test(rel)) return true;
  return false;
}

describe('colour tokens: no hardcoded colour in TypeScript', () => {
  it('has no hex colour literal in any non-exempt .ts/.tsx file under src/', () => {
    const offenders: string[] = [];
    for (const rel of sourceFiles()) {
      if (isExempt(rel)) continue;
      const matches = read(rel).match(HEX);
      if (matches) offenders.push(`${rel}: ${matches.join(', ')}`);
    }
    expect(offenders, `hex literals must move behind a CSS var:\n${offenders.join('\n')}`).toEqual(
      [],
    );
  });

  it('allows hexes in PumpCurve.tsx only as readCssVar fallbacks', () => {
    const src = read(PUMP_CURVE);
    // There must be some — this is the one place a literal is load-bearing.
    expect(src.match(HEX)?.length ?? 0).toBeGreaterThan(0);
    // Remove every `readCssVar('--name', '#hex')` fallback, then assert no hex
    // survives anywhere else in the file.
    const stripped = src.replace(
      /readCssVar\(\s*'[^']+',\s*'#[0-9a-fA-F]{3,8}'\s*\)/g,
      'readCssVar()',
    );
    expect(stripped.match(HEX), 'PumpCurve hexes must only be readCssVar fallbacks').toBeNull();
  });
});

/** Every token this PR migrates from TypeScript, grouped by meaning. */
const TOKENS = [
  // Health bands (lib/format.ts bandColor)
  '--band-healthy', '--band-monitor', '--band-degraded', '--band-highrisk', '--band-critical',
  // Risk (lib/format.ts riskColor)
  '--risk-low', '--risk-elevated', '--risk-high', '--risk-unknown',
  // Model drift (pages/Models.tsx)
  '--drift-stable', '--drift-watch', '--drift-drifting', '--drift-unknown',
  // Compliance (pages/Models.tsx)
  '--compliance-pass', '--compliance-fail', '--on-status',
  // Audit actions (components/AuditTrail.tsx)
  '--audit-created', '--audit-approved', '--audit-rejected', '--audit-default',
  // Contribution deltas (components/ContributionBreakdown.tsx)
  '--delta-adverse-strong', '--delta-adverse', '--delta-favourable',
  // Chart surface (components/PumpCurve.tsx)
  '--chart-bg', '--chart-border', '--chart-text', '--chart-text-dim', '--chart-axis',
  '--chart-grid', '--chart-series', '--chart-point-ok', '--chart-point-watch', '--chart-point-edge',
  // Network twin (pages/NetworkTwin.tsx)
  '--band-unknown', '--map-bg', '--map-node-stroke', '--leak-zone',
  // Operating envelope (pages/AssetTwin.tsx)
  '--envelope-ok', '--envelope-nearlimit', '--envelope-over',
  // Training grade (pages/TrainingSimulator.tsx)
  '--grade-proficient',
  // Auto-update accent (pages/Administration.tsx)
  '--auto-update-ok',
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

describe('colour tokens: styles.css declares every migrated token exactly once', () => {
  const css = read('styles.css');
  for (const name of TOKENS) {
    it(`declares ${name} exactly once`, () => {
      const re = new RegExp(`${escapeRegExp(name)}\\s*:`, 'g');
      expect((css.match(re) ?? []).length).toBe(1);
    });
  }
});

describe('colour tokens: cssVar helper', () => {
  const src = read('lib/cssVar.ts');

  it('exists and exports readCssVar', () => {
    expect(/export\s+function\s+readCssVar\s*\(/.test(src)).toBe(true);
  });

  it('guards against a missing document (SSR)', () => {
    expect(/typeof\s+document\s*===\s*'undefined'/.test(src)).toBe(true);
  });
});

describe('colour tokens: format.ts colour helpers return var()', () => {
  const src = read('lib/format.ts');

  it('bandColor maps every band to a var(--…) string', () => {
    const block = src.match(/bandColor:[^=]*=\s*\{([\s\S]*?)\}/);
    expect(block, 'bandColor object literal must exist').not.toBeNull();
    const values = [...block![1].matchAll(/:\s*'([^']*)'/g)].map((m) => m[1]);
    expect(values.length).toBeGreaterThan(0);
    for (const v of values) expect(v.startsWith('var(--')).toBe(true);
  });

  it('riskColor returns only var(--…) strings', () => {
    const fn = src.match(/function riskColor[\s\S]*?\n\}/);
    expect(fn, 'riskColor function must exist').not.toBeNull();
    const returns = [...fn![0].matchAll(/return\s+'([^']*)'/g)].map((m) => m[1]);
    expect(returns.length).toBeGreaterThan(0);
    for (const v of returns) expect(v.startsWith('var(--')).toBe(true);
  });
});
