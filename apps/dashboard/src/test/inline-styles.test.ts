/**
 * Guardrail: the two inline-style patterns migrated in the "layout utilities"
 * refactor stay migrated, and nothing was left half-done.
 *
 * PR 2 replaces two mechanical inline-style patterns with CSS classes:
 *   - `style={{ textAlign: 'right' }}`                         -> class `cell-num`
 *   - `style={{ justifyContent: 'space-between',
 *               alignItems: 'center' }}`                       -> class `row-split`
 *
 * This suite reads the source as raw text (no CSS or JSX parser dependency) and
 * walks `src/` recursively with plain `readFileSync` + regex. It asserts that:
 *   - no `.tsx` file still contains a right-aligned inline style,
 *   - no `.tsx` file still contains a style object holding both the
 *     space-between and center properties (in either order),
 *   - no file contains an empty inline style object (no leftover `style` with an
 *     empty object after a partial migration),
 *   - the total number of `style={{` occurrences across `src/**\/*.tsx` is at or
 *     below the ceiling (99: it is 180 on main; this PR removes 81). The ceiling
 *     is asserted, not an exact number, so a follow-up PR can lower it further
 *     without editing this test,
 *   - styles.css declares `.cell-num` and `.row-split` exactly once each.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE =
  typeof import.meta.dirname === 'string'
    ? import.meta.dirname
    : path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(HERE, '..');
const STYLES_PATH = path.resolve(SRC_DIR, 'styles.css');

/** Recursively collect every file under `dir`. */
function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

const allFiles = walk(SRC_DIR);
const tsxFiles = allFiles.filter((f) => f.endsWith('.tsx'));

/** All `style={{ ... }}` objects in `text`, returning the inner (between-brace) text. */
function styleObjects(text: string): string[] {
  const re = /style=\{\{([^{}]*)\}\}/g;
  const out: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    out.push(match[1]);
  }
  return out;
}

describe('dashboard inline-style migration', () => {
  it('has no .tsx file with a right-aligned inline style', () => {
    const offenders = tsxFiles.filter((f) => {
      const text = readFileSync(f, 'utf8');
      return text.includes("textAlign: 'right'") || text.includes('textAlign: "right"');
    });
    expect(offenders, `textAlign right must be migrated to .cell-num`).toEqual([]);
  });

  it('has no .tsx file with a style object holding both space-between and center', () => {
    const offenders = tsxFiles.filter((f) => {
      const text = readFileSync(f, 'utf8');
      return styleObjects(text).some((obj) => {
        const hasSpaceBetween =
          obj.includes("justifyContent: 'space-between'") ||
          obj.includes('justifyContent: "space-between"');
        const hasCenter =
          obj.includes("alignItems: 'center'") || obj.includes('alignItems: "center"');
        return hasSpaceBetween && hasCenter;
      });
    });
    expect(offenders, `split-row pairs must be migrated to .row-split`).toEqual([]);
  });

  it('has no empty inline style object anywhere in src', () => {
    const offenders = allFiles.filter((f) => {
      const text = readFileSync(f, 'utf8');
      return /style=\{\{\s*\}\}/.test(text);
    });
    expect(offenders, `empty style objects must be removed entirely`).toEqual([]);
  });

  it('keeps the total number of style={{ at or below the ceiling', () => {
    const CEILING = 99;
    let total = 0;
    for (const f of tsxFiles) {
      const text = readFileSync(f, 'utf8');
      total += (text.match(/style=\{\{/g) ?? []).length;
    }
    expect(total, `style={{ count must be <= ${CEILING}`).toBeLessThanOrEqual(CEILING);
  });

  it('declares .cell-num and .row-split exactly once each in styles.css', () => {
    const css = readFileSync(STYLES_PATH, 'utf8');
    expect((css.match(/\.cell-num\s*\{/g) ?? []).length, '.cell-num declared once').toBe(1);
    expect((css.match(/\.row-split\s*\{/g) ?? []).length, '.row-split declared once').toBe(1);
  });
});
