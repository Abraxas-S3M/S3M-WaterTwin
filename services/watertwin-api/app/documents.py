"""Lightweight seeded document store + keyword retrieval (advisory, read-only).

Loads the seeded RO operations documents under ``data/`` (HP-pump manual excerpt,
pump isolation / membrane CIP / cartridge-filter replacement procedures and a
maintenance-history record) and exposes a small, honest keyword retrieval used by
the operations assistant to ground its answers in real documents.

NOTE ON RETRIEVAL FIDELITY: retrieval here is deliberately **keyword-based** --
it tokenizes the query and scores documents by term overlap against the title,
tags and body (with a modest title/tag boost). This is honest and dependency-
free. Semantic / pgvector embedding retrieval is a documented later hardening
upgrade; it is intentionally NOT implemented yet so the platform never overstates
its retrieval capability.

Nothing in this module writes to any control system; it only reads seeded text.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field

from canonical_water_model import DocumentRef, DocumentType

#: Root of the seeded document corpus. Resolves to ``<repo>/data`` by default and
#: can be overridden for tests via ``WATERTWIN_DATA_DIR``.
_DEFAULT_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
)
DATA_DIR = os.environ.get("WATERTWIN_DATA_DIR", _DEFAULT_DATA_DIR)

#: Subdirectory -> document type mapping for the seeded corpus.
_TYPE_BY_DIR: dict[str, DocumentType] = {
    "manuals": DocumentType.manual,
    "procedures": DocumentType.procedure,
    "maintenance": DocumentType.maintenance_record,
}

#: Very small English stop-word set so keyword scoring ignores filler tokens.
_STOP_WORDS = {
    "the", "a", "an", "of", "to", "for", "and", "or", "is", "are", "in", "on",
    "at", "by", "with", "what", "why", "how", "which", "does", "do", "this",
    "that", "it", "its", "be", "as", "from", "into", "if", "when", "we", "you",
    "i", "me", "my", "give", "show", "get",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _tokenize(text: str) -> list[str]:
    """Lowercase word/id tokens (keeps hyphenated ids like ``ast-hpp-01``)."""
    return _WORD_RE.findall(text.lower())


def _keywords(text: str) -> list[str]:
    return [t for t in _tokenize(text) if t not in _STOP_WORDS and len(t) > 1]


@dataclass
class _Document:
    """A loaded seeded document (full body kept in memory; corpus is tiny)."""

    document_id: str
    title: str
    document_type: DocumentType
    path: str
    body: str
    tags: list[str] = field(default_factory=list)
    _token_counts: dict[str, int] = field(default_factory=dict)

    def to_ref(self, score: float | None = None, snippet: str | None = None) -> DocumentRef:
        return DocumentRef(
            document_id=self.document_id,
            title=self.title,
            document_type=self.document_type,
            path=self.path,
            tags=list(self.tags),
            score=score,
            snippet=snippet,
        )


def _first_heading(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return fallback


def _extract_document_id(body: str, fallback: str) -> str:
    match = re.search(r"Document ID:\s*([A-Za-z0-9\-]+)", body)
    if match:
        return match.group(1)
    return fallback


def _extract_tags(body: str) -> list[str]:
    """Derive tags from asset ids + a small keyword vocabulary in the body."""
    tags: list[str] = []
    for asset in re.findall(r"AST-[A-Z]+-\d+", body):
        if asset not in tags:
            tags.append(asset)
    vocab = [
        "pump", "membrane", "cip", "cleaning", "cartridge", "filter",
        "isolation", "lockout", "bearing", "seal", "vibration", "scaling",
        "fouling", "maintenance", "erd",
    ]
    lower = body.lower()
    for word in vocab:
        if word in lower and word not in tags:
            tags.append(word)
    return tags


class DocumentStore:
    """In-memory store of the seeded documents with keyword retrieval."""

    def __init__(self, data_dir: str = DATA_DIR) -> None:
        self._data_dir = data_dir
        self._lock = threading.RLock()
        self._docs: dict[str, _Document] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            self._docs.clear()
            for sub, doc_type in _TYPE_BY_DIR.items():
                dir_path = os.path.join(self._data_dir, sub)
                if not os.path.isdir(dir_path):
                    continue
                for name in sorted(os.listdir(dir_path)):
                    if not name.lower().endswith((".md", ".txt")):
                        continue
                    path = os.path.join(dir_path, name)
                    try:
                        with open(path, "r", encoding="utf-8") as fh:
                            body = fh.read()
                    except OSError:
                        continue
                    rel_path = os.path.join("data", sub, name)
                    fallback_id = f"{sub[:3].upper()}-{os.path.splitext(name)[0]}"
                    doc_id = _extract_document_id(body, fallback_id)
                    title = _first_heading(body, os.path.splitext(name)[0])
                    doc = _Document(
                        document_id=doc_id,
                        title=title,
                        document_type=doc_type,
                        path=rel_path,
                        body=body,
                        tags=_extract_tags(body),
                    )
                    counts: dict[str, int] = {}
                    for tok in _keywords(f"{title} {' '.join(doc.tags)} {body}"):
                        counts[tok] = counts.get(tok, 0) + 1
                    doc._token_counts = counts
                    self._docs[doc.document_id] = doc

    def reload(self) -> None:
        self._load()

    def list(self) -> list[DocumentRef]:
        with self._lock:
            return [d.to_ref() for d in sorted(self._docs.values(), key=lambda d: d.document_id)]

    def get(self, document_id: str) -> dict | None:
        """Return the full document (metadata + body) or ``None`` if unknown."""
        with self._lock:
            doc = self._docs.get(document_id)
            if doc is None:
                return None
            return {
                "document_id": doc.document_id,
                "title": doc.title,
                "document_type": doc.document_type.value,
                "path": doc.path,
                "tags": list(doc.tags),
                "content": doc.body,
            }

    def _snippet(self, doc: _Document, query_tokens: set[str]) -> str:
        """A short excerpt around the first query-term hit (or the intro)."""
        for raw_line in doc.body.splitlines():
            line = raw_line.strip().lstrip("#").strip()
            if not line or line.startswith("-") or line.startswith("|"):
                continue
            if query_tokens & set(_keywords(line)):
                return line[:240]
        # Fall back to the first substantive prose line.
        for raw_line in doc.body.splitlines():
            line = raw_line.strip()
            if line and not line.startswith(("#", "-", "|", ">")):
                return line[:240]
        return doc.title

    def retrieve(self, query: str, k: int = 3) -> list[DocumentRef]:
        """Return up to ``k`` documents ranked by keyword relevance to ``query``.

        Scoring: for each distinct query keyword, add its body term-frequency
        plus a boost when it appears in the document title or tags. Documents
        with zero overlap are excluded so the assistant never cites an
        irrelevant document. Keyword-based only (see module docstring).
        """
        q_tokens = _keywords(query)
        if not q_tokens:
            return []
        q_set = set(q_tokens)
        scored: list[tuple[float, _Document]] = []
        with self._lock:
            for doc in self._docs.values():
                title_tokens = set(_keywords(doc.title))
                tag_tokens = {t.lower() for t in doc.tags}
                score = 0.0
                for tok in q_set:
                    tf = doc._token_counts.get(tok, 0)
                    if tf:
                        score += 1.0 + min(tf, 5) * 0.5
                    if tok in title_tokens:
                        score += 3.0
                    if tok in tag_tokens:
                        score += 2.0
                if score > 0:
                    scored.append((score, doc))
        scored.sort(key=lambda item: (item[0], item[1].document_id), reverse=True)
        refs: list[DocumentRef] = []
        for score, doc in scored[: max(0, k)]:
            refs.append(doc.to_ref(score=round(score, 3), snippet=self._snippet(doc, q_set)))
        return refs


#: Process-wide default store over the seeded corpus.
_store: DocumentStore | None = None
_store_lock = threading.RLock()


def get_store() -> DocumentStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DocumentStore()
        return _store


def list_documents() -> list[DocumentRef]:
    return get_store().list()


def get_document(document_id: str) -> dict | None:
    return get_store().get(document_id)


def retrieve(query: str, k: int = 3) -> list[DocumentRef]:
    """Keyword-retrieve up to ``k`` seeded documents relevant to ``query``."""
    return get_store().retrieve(query, k)
