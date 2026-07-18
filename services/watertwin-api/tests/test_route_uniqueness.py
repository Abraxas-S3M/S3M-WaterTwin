"""Guardrail: every (path, method) is registered exactly once.

FastAPI resolves the *first* matching registration for a path, so a duplicate
route silently shadows the later handler. That is exactly what made the model
governance registry (``GET /api/v1/models``) unreachable: a second handler on
the same path was never reached and its ``count`` payload never shipped.

This test iterates ``app.routes`` and asserts there are no duplicate
``(path, method)`` pairs, so this class of bug cannot recur.
"""

from __future__ import annotations

from collections import Counter

from app.main import app


def _route_method_pairs() -> list[tuple[str, str]]:
    """Return every registered ``(path, method)`` pair across the app."""
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or not methods:
            continue
        for method in methods:
            pairs.append((path, method))
    return pairs


def test_no_duplicate_route_registrations() -> None:
    pairs = _route_method_pairs()
    duplicates = {pair: count for pair, count in Counter(pairs).items() if count > 1}
    assert not duplicates, f"duplicate (path, method) registrations: {duplicates}"


def test_models_registry_is_the_only_models_handler() -> None:
    # Regression lock for the specific bug: exactly one GET /api/v1/models.
    models_get = [
        pair for pair in _route_method_pairs() if pair == ("/api/v1/models", "GET")
    ]
    assert len(models_get) == 1
