/**
 * Guardrail: the design-token layer in styles.css is present and additive.
 *
 * PR "dashboard-token-layer" is purely additive: it appends CSS custom
 * properties to `:root`, adds a direction-aware `[dir="rtl"]` chamfer block, a
 * declared-but-unconsumed `[data-tier="workbench"]` block, and a
 * reduced-motion media query. It must NOT disturb any of the 14 pre-existing
 * `:root` variables or their values.
 *
 * This suite reads styles.css as raw text (no CSS parser dependency) and
 * asserts, with hardcoded expectations, that:
 *   - every pre-existing variable still holds its exact current value,
 *   - every new token is declared exactly once in the main `:root` block,
 *   - the contrast-warning comment precedes `--ink-3`,
 *   - a `[dir="rtl"]` block redeclares all three `--cut-*` tokens,
 *   - `--ok` and `--signal-ok` are both present and distinct, and
 *   - the file contains no `@import` and no `localStorage`.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE =
  typeof import.meta.dirname === 'string'
    ? import.meta.dirname
    : path.dirname(fileURLToPath(import.meta.url));
const STYLES_PATH = path.resolve(HERE, '..', 'styles.css');
const css = readFileSync(STYLES_PATH, 'utf8');

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** The first (main) `:root { ... }` block; it contains no nested braces. */
function mainRootBlock(text: string): string {
  const match = text.match(/:root\s*\{([^}]*)\}/);
  if (!match) throw new Error('could not locate the main :root block');
  return match[1];
}

/** Count declaration occurrences (`--name:`) within a chunk of CSS. */
function declCount(chunk: string, name: string): number {
  const re = new RegExp(`${escapeRegExp(name)}\\s*:`, 'g');
  return (chunk.match(re) ?? []).length;
}

/** The 14 pre-existing :root variables and their exact current values. */
const PRE_EXISTING: Record<string, string> = {
  '--bg': '#0b1017',
  '--bg-elev': '#131a24',
  '--bg-elev-2': '#1a2330',
  '--border': '#26303f',
  '--text': '#e6edf3',
  '--text-dim': '#8b95a5',
  '--accent': '#38bdf8',
  '--accent-strong': '#0ea5e9',
  '--danger': '#e74c3c',
  '--warn': '#f1c40f',
  '--ok': '#2ecc71',
  '--radius': '10px',
  '--shadow': '0 1px 3px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.25)',
  '--accent-contrast': '#04222f',
};

/** Every new token this PR adds. */
const NEW_TOKENS = [
  // Ground and surface
  '--ground-deep', '--ground', '--ground-lit',
  '--panel-a', '--panel-b', '--inset-a', '--inset-b',
  // Ink
  '--ink', '--ink-2', '--ink-3',
  // Edge
  '--edge', '--edge-hot',
  // Signal
  '--aqua', '--alert-hi', '--alert-md', '--alert-lo', '--signal-ok',
  // Spacing
  '--sp-1', '--sp-2', '--sp-3', '--sp-4', '--sp-5', '--sp-6', '--sp-8', '--sp-10',
  // Type scale
  '--fs-meta', '--fs-cap', '--fs-body', '--fs-lead', '--fs-h3', '--fs-h2', '--fs-stat', '--fs-big',
  '--lh-tight', '--lh-body',
  '--f-disp', '--f-body', '--f-mono',
  // Elevation and decoration
  '--elev-1', '--elev-2', '--bloom', '--bloom-0', '--lip',
  // Chamfer geometry
  '--chamfer', '--cut-br', '--cut-lean', '--cut-tag',
  // Motion
  '--dur-fast', '--dur-base', '--dur-slow', '--ease',
];

describe('dashboard design-token layer', () => {
  it('preserves all 14 pre-existing :root variables with their exact values', () => {
    for (const [name, value] of Object.entries(PRE_EXISTING)) {
      const re = new RegExp(`${escapeRegExp(name)}\\s*:\\s*${escapeRegExp(value)}\\s*;`);
      expect(re.test(css), `${name} must still be ${value}`).toBe(true);
    }
  });

  it('declares each new token exactly once in the main :root block', () => {
    const root = mainRootBlock(css);
    for (const name of NEW_TOKENS) {
      expect(declCount(root, name), `${name} must be declared exactly once in :root`).toBe(1);
    }
  });

  it('declares --ink-3 with the contrast-warning comment preceding it', () => {
    const declIndex = css.search(/--ink-3\s*:/);
    expect(declIndex, '--ink-3 must be declared').toBeGreaterThan(-1);
    const commentIndex = css.indexOf('Permitted for uppercase metadata');
    expect(commentIndex, 'contrast-warning comment must exist').toBeGreaterThan(-1);
    expect(commentIndex, 'contrast-warning comment must precede --ink-3').toBeLessThan(declIndex);
  });

  it('has a [dir="rtl"] block that redeclares all three --cut-* tokens', () => {
    const match = css.match(/\[dir="rtl"\]\s*\{([^}]*)\}/);
    expect(match, 'a [dir="rtl"] block must exist').not.toBeNull();
    const block = match![1];
    for (const name of ['--cut-br', '--cut-lean', '--cut-tag']) {
      expect(declCount(block, name), `[dir="rtl"] must redeclare ${name}`).toBe(1);
    }
  });

  it('has --ok and --signal-ok as both present and distinct declarations', () => {
    expect(/--ok\s*:\s*#2ecc71\s*;/.test(css), '--ok must be present with its value').toBe(true);
    expect(/--signal-ok\s*:\s*#5fe08a\s*;/.test(css), '--signal-ok must be present with its value').toBe(true);
    const okIndex = css.search(/--ok\s*:/);
    const signalOkIndex = css.search(/--signal-ok\s*:/);
    expect(okIndex).toBeGreaterThan(-1);
    expect(signalOkIndex).toBeGreaterThan(-1);
    expect(okIndex, '--ok and --signal-ok must be distinct declarations').not.toBe(signalOkIndex);
  });

  it('contains no @import and no localStorage', () => {
    expect(css.includes('@import'), 'styles.css must not use @import').toBe(false);
    expect(/localStorage/.test(css), 'styles.css must not reference localStorage').toBe(false);
  });
});
