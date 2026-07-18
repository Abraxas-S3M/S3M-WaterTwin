"""Guardrail: no duplicated-fragment corruption in Python source.

A botched merge can silently glue two copies of a module together. The result
often still *compiles* — Python is happy with a second bare docstring, a second
``from __future__`` import folded in at the top, or a function/class simply
redefined lower down (the last definition quietly wins). Those are exactly the
kinds of duplication that slip through code review and stay undetected, which is
how the model-governance route was shadowed and how ``en.json`` kept a duplicate
key. This test makes that class of corruption impossible to merge.

Scope and division of labour
----------------------------
This walks every ``.py`` file under ``packages/`` and ``services/`` and asserts,
per file:

* at most one module-level docstring,
* at most one ``from __future__`` import, and
* no duplicate top-level function or class name.

These are all *silent* problems: the file still compiles. Files that do **not**
compile are a different (louder) failure mode already gated by the CI
``compile-guard`` job (``python -m compileall packages services ...``), so they
are skipped here rather than double-reported. Keeping the two guards separate
means each one fails for exactly one reason.
"""

from __future__ import annotations

import ast
import os
from collections import Counter

# services/watertwin-api/tests/ -> services/watertwin-api/ -> services/ -> repo
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCAN_ROOTS = ("packages", "services")
_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def _iter_python_files() -> list[str]:
    files: list[str] = []
    for root in SCAN_ROOTS:
        base = os.path.join(REPO_ROOT, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                if name.endswith(".py"):
                    files.append(os.path.join(dirpath, name))
    return sorted(files)


def _parse_compilable(path: str) -> ast.Module | None:
    """Parse ``path`` only if it fully compiles.

    Returns the AST for a compilable file, or ``None`` for a file that raises a
    ``SyntaxError`` (those are the ``compile-guard`` job's responsibility). Full
    ``compile`` — not just ``ast.parse`` — is used so a misplaced late
    ``from __future__`` import (a classic bad-merge artefact) is treated as the
    syntax failure it is rather than analysed here.
    """
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    try:
        compile(source, path, "exec")
    except SyntaxError:
        return None
    return ast.parse(source)


def _module_docstring_count(tree: ast.Module) -> int:
    """Number of bare module-level string-literal statements."""
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _future_import_count(tree: ast.Module) -> int:
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    )


def _duplicate_top_level_defs(tree: ast.Module) -> dict[str, int]:
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return {name: count for name, count in Counter(names).items() if count > 1}


def _rel(path: str) -> str:
    return os.path.relpath(path, REPO_ROOT)


def test_at_most_one_module_docstring_per_file() -> None:
    offenders = {
        _rel(path): count
        for path in _iter_python_files()
        if (tree := _parse_compilable(path)) is not None
        and (count := _module_docstring_count(tree)) > 1
    }
    assert not offenders, f"files with more than one module-level docstring: {offenders}"


def test_at_most_one_future_import_per_file() -> None:
    offenders = {
        _rel(path): count
        for path in _iter_python_files()
        if (tree := _parse_compilable(path)) is not None
        and (count := _future_import_count(tree)) > 1
    }
    assert not offenders, f"files with more than one 'from __future__' import: {offenders}"


def test_no_duplicate_top_level_defs_per_file() -> None:
    offenders = {
        _rel(path): dups
        for path in _iter_python_files()
        if (tree := _parse_compilable(path)) is not None
        and (dups := _duplicate_top_level_defs(tree))
    }
    assert not offenders, f"files with duplicate top-level function/class names: {offenders}"


def test_scan_actually_found_python_files() -> None:
    # Guard against the guard silently walking nothing (bad path, empty tree).
    assert len(_iter_python_files()) > 50
