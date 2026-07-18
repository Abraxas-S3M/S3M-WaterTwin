/**
 * Guardrail: no duplicated-fragment corruption in the dashboard source.
 *
 * A botched merge can silently glue two copies of a file together. The result
 * frequently still parses — a symbol imported twice from the same module, a
 * `const` or `function` redeclared at the top level, or a JSON object with a
 * repeated key (`JSON.parse` silently keeps the last one, which is exactly how
 * `en.json` stayed broken and undetected). This suite makes that class of
 * corruption impossible to merge.
 *
 * For every `.ts`/`.tsx` file under `src/` it asserts:
 *   - no symbol is imported twice from the same module, and
 *   - no top-level `const` or `function` is declared more than once.
 *
 * For every JSON file under `src/i18n/locales` it asserts the file parses with a
 * duplicate-key-REJECTING parser (plain `JSON.parse` cannot see the problem).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import ts from 'typescript';

const HERE =
  typeof import.meta.dirname === 'string'
    ? import.meta.dirname
    : path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(HERE, '..');
const LOCALES_DIR = path.join(SRC_DIR, 'i18n', 'locales');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const allFiles = walk(SRC_DIR);
const sourceFiles = allFiles.filter((f) => /\.tsx?$/.test(f));
const localeFiles = walk(LOCALES_DIR).filter((f) => f.endsWith('.json'));

function rel(file: string): string {
  return path.relative(SRC_DIR, file);
}

function parse(file: string): ts.SourceFile {
  const source = readFileSync(file, 'utf8');
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, kind);
}

/** Every symbol name each import statement pulls from its module. */
function importsByModule(sf: ts.SourceFile): Map<string, string[]> {
  const byModule = new Map<string, string[]>();
  for (const st of sf.statements) {
    if (!ts.isImportDeclaration(st) || !st.importClause) continue;
    if (!ts.isStringLiteral(st.moduleSpecifier)) continue;
    const mod = st.moduleSpecifier.text;
    const names: string[] = [];
    const clause = st.importClause;
    if (clause.name) names.push(clause.name.text); // default import
    if (clause.namedBindings) {
      if (ts.isNamespaceImport(clause.namedBindings)) {
        names.push(`* as ${clause.namedBindings.name.text}`);
      } else {
        for (const el of clause.namedBindings.elements) names.push(el.name.text);
      }
    }
    const existing = byModule.get(mod) ?? [];
    existing.push(...names);
    byModule.set(mod, existing);
  }
  return byModule;
}

function collectBindingNames(name: ts.BindingName, out: string[]): void {
  if (ts.isIdentifier(name)) {
    out.push(name.text);
  } else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
    for (const el of name.elements) {
      if (ts.isBindingElement(el)) collectBindingNames(el.name, out);
    }
  }
}

/** Names of top-level `const` and `function` declarations. */
function topLevelDeclarations(sf: ts.SourceFile): string[] {
  const names: string[] = [];
  for (const st of sf.statements) {
    if (ts.isVariableStatement(st)) {
      const isConst = (st.declarationList.flags & ts.NodeFlags.Const) !== 0;
      if (!isConst) continue;
      for (const decl of st.declarationList.declarations) {
        collectBindingNames(decl.name, names);
      }
    } else if (ts.isFunctionDeclaration(st) && st.name) {
      names.push(st.name.text);
    }
  }
  return names;
}

function duplicates(values: string[]): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const v of values) {
    if (seen.has(v)) dup.add(v);
    seen.add(v);
  }
  return [...dup];
}

/**
 * Minimal recursive-descent JSON parser that throws on a duplicate object key
 * at any nesting depth. `JSON.parse` silently keeps the last duplicate, so it
 * cannot be used to detect this corruption.
 */
function parseJsonRejectingDuplicateKeys(text: string, label: string): unknown {
  let i = 0;
  const n = text.length;
  const fail = (msg: string): never => {
    throw new Error(`${label}: ${msg} (offset ${i})`);
  };
  const skipWs = () => {
    while (i < n && (text[i] === ' ' || text[i] === '\t' || text[i] === '\n' || text[i] === '\r')) i++;
  };
  const parseString = (): string => {
    i++; // opening quote
    let s = '';
    while (i < n) {
      const c = text[i++];
      if (c === '"') return s;
      if (c === '\\') {
        const e = text[i++];
        if (e === 'u') {
          s += String.fromCharCode(parseInt(text.slice(i, i + 4), 16));
          i += 4;
        } else {
          const map: Record<string, string> = {
            '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t',
          };
          s += map[e] ?? e;
        }
      } else {
        s += c;
      }
    }
    return fail('unterminated string');
  };
  const parseNumber = (): number => {
    const start = i;
    if (text[i] === '-') i++;
    while (i < n && text[i] >= '0' && text[i] <= '9') i++;
    if (text[i] === '.') {
      i++;
      while (i < n && text[i] >= '0' && text[i] <= '9') i++;
    }
    if (text[i] === 'e' || text[i] === 'E') {
      i++;
      if (text[i] === '+' || text[i] === '-') i++;
      while (i < n && text[i] >= '0' && text[i] <= '9') i++;
    }
    return Number(text.slice(start, i));
  };
  const parseValue = (): unknown => {
    skipWs();
    const c = text[i];
    if (c === '{') return parseObject();
    if (c === '[') return parseArray();
    if (c === '"') return parseString();
    if (c === '-' || (c >= '0' && c <= '9')) return parseNumber();
    if (text.startsWith('true', i)) { i += 4; return true; }
    if (text.startsWith('false', i)) { i += 5; return false; }
    if (text.startsWith('null', i)) { i += 4; return null; }
    return fail('unexpected token');
  };
  const parseArray = (): unknown[] => {
    i++; // [
    const arr: unknown[] = [];
    skipWs();
    if (text[i] === ']') { i++; return arr; }
    for (;;) {
      arr.push(parseValue());
      skipWs();
      if (text[i] === ',') { i++; continue; }
      if (text[i] === ']') { i++; return arr; }
      return fail("expected ',' or ']'");
    }
  };
  const parseObject = (): Record<string, unknown> => {
    i++; // {
    const obj: Record<string, unknown> = {};
    const keys = new Set<string>();
    skipWs();
    if (text[i] === '}') { i++; return obj; }
    for (;;) {
      skipWs();
      if (text[i] !== '"') return fail('expected string key');
      const key = parseString();
      if (keys.has(key)) return fail(`duplicate key ${JSON.stringify(key)}`);
      keys.add(key);
      skipWs();
      if (text[i] !== ':') return fail("expected ':'");
      i++;
      obj[key] = parseValue();
      skipWs();
      if (text[i] === ',') { i++; continue; }
      if (text[i] === '}') { i++; return obj; }
      return fail("expected ',' or '}'");
    }
  };
  const value = parseValue();
  skipWs();
  if (i < n) fail('trailing content after JSON value');
  return value;
}

describe('dashboard source integrity', () => {
  it('discovers source files to check (guards against an empty scan)', () => {
    expect(sourceFiles.length).toBeGreaterThan(20);
    expect(localeFiles.length).toBeGreaterThan(0);
  });

  it('imports no symbol twice from the same module', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles) {
      const sf = parse(file);
      for (const [mod, names] of importsByModule(sf)) {
        const dup = duplicates(names);
        if (dup.length) offenders.push(`${rel(file)}: [${dup.join(', ')}] from '${mod}'`);
      }
    }
    expect(offenders, `symbols imported twice from the same module:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('declares no top-level const or function more than once', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles) {
      const sf = parse(file);
      const dup = duplicates(topLevelDeclarations(sf));
      if (dup.length) offenders.push(`${rel(file)}: [${dup.join(', ')}]`);
    }
    expect(offenders, `duplicate top-level declarations:\n${offenders.join('\n')}`).toEqual([]);
  });

  it('has no duplicate keys in any i18n locale JSON', () => {
    for (const file of localeFiles) {
      const text = readFileSync(file, 'utf8');
      expect(() => parseJsonRejectingDuplicateKeys(text, rel(file))).not.toThrow();
    }
  });
});
