"""Document store + keyword retrieval (advisory, read-only).

Holds two kinds of grounding document side by side:

* **platform-seeded** documents shipped under ``data/`` (HP-pump manual excerpt,
  pump isolation / membrane CIP / cartridge-filter replacement procedures and a
  maintenance-history record); and
* **customer-supplied** documents a customer uploaded (parsed to text + chunks by
  the ``watertwin-ingest`` service). Each customer document is scoped to a
  ``tenant_id`` and carries its ``ingest_id``, ``sha256``, ``uploader`` and, once
  approved, ``approved_by``.

Two invariants protect customers from each other and from unreviewed content:

* **Tenant scoping on every read path** — :meth:`DocumentStore.retrieve`,
  :meth:`DocumentStore.list` and :meth:`DocumentStore.get` never return another
  tenant's customer document. Platform-seeded documents are common to all.
* **Approval gate** — an uploaded document is not retrievable by the assistant
  until it has been approved (same posture as every other operator decision).

NOTE ON RETRIEVAL FIDELITY: retrieval here is deliberately **keyword-based** --
it tokenizes the query and scores documents by term overlap against the title,
tags and body (with a modest title/tag boost). This is honest and dependency-
free. Semantic / pgvector embedding retrieval is a documented later hardening
upgrade; it is intentionally NOT implemented yet so the platform never overstates
its retrieval capability.

Nothing in this module writes to any control system; it only reads text.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from canonical_water_model import DocumentProvenance, DocumentRef, DocumentType

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
            provenance=DocumentProvenance.platform_seeded,
        )


#: Approval states for a customer-supplied document (mirrors the operator
#: approval posture used everywhere else in the platform).
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


@dataclass
class _CustomerChunk:
    """A single stored chunk of a customer document with its source location."""

    chunk_id: str
    text: str
    char_start: int
    char_end: int
    page: Optional[int] = None
    section: Optional[str] = None
    _token_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _CustomerDocument:
    """A customer-uploaded, tenant-scoped, approval-gated grounding document.

    The full text is kept as ordered :class:`_CustomerChunk` objects so a
    citation can resolve to a real page/section + character offset in the file.
    ``provenance`` is always customer-supplied.
    """

    document_id: str
    tenant_id: str
    ingest_id: str
    title: str
    document_type: DocumentType
    filename: str
    sha256: str
    uploader: str
    chunks: list[_CustomerChunk] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    approval_status: str = APPROVAL_PENDING
    approved_by: Optional[str] = None
    _token_counts: dict[str, int] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.approval_status == APPROVAL_APPROVED

    @property
    def body(self) -> str:
        """Reconstructed full text (chunks in order)."""
        return "\n\n".join(c.text for c in self.chunks)

    def _location(self, chunk: _CustomerChunk) -> str:
        bits: list[str] = []
        if chunk.page is not None:
            bits.append(f"p.{chunk.page}")
        if chunk.section:
            bits.append(f"§ {chunk.section}")
        bits.append(f"chars {chunk.char_start}-{chunk.char_end}")
        return ", ".join(bits)

    def to_ref(
        self,
        *,
        chunk: Optional[_CustomerChunk] = None,
        score: float | None = None,
        snippet: str | None = None,
    ) -> DocumentRef:
        chunk = chunk or (self.chunks[0] if self.chunks else None)
        page = chunk.page if chunk else None
        section = chunk.section if chunk else None
        location = self._location(chunk) if chunk else None
        # A resolvable, non-filesystem reference: tenant + ingest id + offsets.
        path = f"customer://{self.tenant_id}/{self.ingest_id}"
        if chunk is not None:
            path = f"{path}#{chunk.chunk_id}"
        return DocumentRef(
            document_id=self.document_id,
            title=self.title,
            document_type=self.document_type,
            path=path,
            tags=list(self.tags),
            score=score,
            snippet=snippet,
            provenance=DocumentProvenance.customer_supplied,
            page=page,
            section=section,
            location=location,
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
    """In-memory store of seeded + customer documents with keyword retrieval."""

    def __init__(self, data_dir: str = DATA_DIR) -> None:
        self._data_dir = data_dir
        self._lock = threading.RLock()
        self._docs: dict[str, _Document] = {}
        #: Customer-supplied documents, keyed by document id (tenant on the doc).
        self._customer_docs: dict[str, _CustomerDocument] = {}
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
        """Reload the seeded corpus (customer documents are left untouched)."""
        self._load()

    # --- customer document ingestion + approval gate ------------------------

    def add_customer_document(
        self,
        *,
        tenant_id: str,
        ingest_id: str,
        filename: str,
        title: str,
        uploader: str,
        sha256: str,
        chunks: list[dict[str, Any]],
        document_type: DocumentType = DocumentType.procedure,
        document_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> str:
        """Register a parsed customer document as ``pending`` (not yet retrievable).

        ``chunks`` are the parser's ``as_store_chunks()`` dicts (``text``, ``page``,
        ``section``, ``char_start``, ``char_end``). The document is scoped to
        ``tenant_id`` and stays out of the assistant's reach until approved.
        Returns the assigned ``document_id``.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for a customer document")
        if not chunks:
            raise ValueError("a customer document must have at least one chunk")
        doc_id = document_id or f"CUST-{ingest_id}"
        stored_chunks: list[_CustomerChunk] = []
        agg_counts: dict[str, int] = {}
        for idx, raw in enumerate(chunks):
            text = str(raw.get("text", ""))
            chunk = _CustomerChunk(
                chunk_id=str(raw.get("chunk_id") or f"{doc_id}:c{idx}"),
                text=text,
                char_start=int(raw.get("char_start", 0)),
                char_end=int(raw.get("char_end", len(text))),
                page=raw.get("page"),
                section=raw.get("section"),
            )
            counts: dict[str, int] = {}
            for tok in _keywords(text):
                counts[tok] = counts.get(tok, 0) + 1
                agg_counts[tok] = agg_counts.get(tok, 0) + 1
            chunk._token_counts = counts
            stored_chunks.append(chunk)
        derived_tags = list(tags or [])
        for tok in _keywords(title):
            if tok not in agg_counts:
                agg_counts[tok] = agg_counts.get(tok, 0) + 1
        doc = _CustomerDocument(
            document_id=doc_id,
            tenant_id=tenant_id,
            ingest_id=ingest_id,
            title=title,
            document_type=document_type,
            filename=filename,
            sha256=sha256,
            uploader=uploader,
            chunks=stored_chunks,
            tags=derived_tags,
            approval_status=APPROVAL_PENDING,
        )
        doc._token_counts = agg_counts
        with self._lock:
            self._customer_docs[doc_id] = doc
        return doc_id

    def _customer_doc_for(
        self, document_id: str, tenant_id: Optional[str]
    ) -> Optional[_CustomerDocument]:
        """Return the customer doc iff it exists AND belongs to ``tenant_id``."""
        doc = self._customer_docs.get(document_id)
        if doc is None:
            return None
        if tenant_id is None or doc.tenant_id != tenant_id:
            return None
        return doc

    def approve_customer_document(
        self, document_id: str, *, tenant_id: str, approved_by: str
    ) -> bool:
        """Approve a customer document so the assistant may retrieve it.

        Tenant-scoped: approving another tenant's document is refused (returns
        ``False``, never crosses the boundary).
        """
        with self._lock:
            doc = self._customer_doc_for(document_id, tenant_id)
            if doc is None:
                return False
            doc.approval_status = APPROVAL_APPROVED
            doc.approved_by = approved_by
            return True

    def reject_customer_document(
        self, document_id: str, *, tenant_id: str, rejected_by: str
    ) -> bool:
        """Reject a customer document (kept, never retrievable). Tenant-scoped."""
        with self._lock:
            doc = self._customer_doc_for(document_id, tenant_id)
            if doc is None:
                return False
            doc.approval_status = APPROVAL_REJECTED
            doc.approved_by = rejected_by
            return True

    # --- reads (tenant-scoped) ----------------------------------------------

    def list(self, tenant_id: Optional[str] = None) -> list[DocumentRef]:
        """List available documents.

        Always includes the platform-seeded corpus. When ``tenant_id`` is given
        it also includes that tenant's customer documents (any status); a
        customer document is never visible to another tenant.
        """
        with self._lock:
            refs = [
                d.to_ref() for d in sorted(self._docs.values(), key=lambda d: d.document_id)
            ]
            if tenant_id is not None:
                customer = [
                    d for d in self._customer_docs.values() if d.tenant_id == tenant_id
                ]
                refs.extend(
                    d.to_ref() for d in sorted(customer, key=lambda d: d.document_id)
                )
            return refs

    def get(self, document_id: str, tenant_id: Optional[str] = None) -> dict | None:
        """Return the full document (metadata + body) or ``None`` if unknown.

        A customer document is only returned to a caller in its own tenant; a
        cross-tenant fetch reports ``None`` (indistinguishable from not-found).
        """
        with self._lock:
            doc = self._docs.get(document_id)
            if doc is not None:
                return {
                    "document_id": doc.document_id,
                    "title": doc.title,
                    "document_type": doc.document_type.value,
                    "path": doc.path,
                    "tags": list(doc.tags),
                    "content": doc.body,
                    "provenance": DocumentProvenance.platform_seeded.value,
                }
            cust = self._customer_doc_for(document_id, tenant_id)
            if cust is None:
                return None
            return {
                "document_id": cust.document_id,
                "title": cust.title,
                "document_type": cust.document_type.value,
                "path": f"customer://{cust.tenant_id}/{cust.ingest_id}",
                "tags": list(cust.tags),
                "content": cust.body,
                "provenance": DocumentProvenance.customer_supplied.value,
                "tenant_id": cust.tenant_id,
                "ingest_id": cust.ingest_id,
                "sha256": cust.sha256,
                "uploader": cust.uploader,
                "approval_status": cust.approval_status,
                "approved_by": cust.approved_by,
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

    def _score_tokens(
        self, q_set: set[str], counts: dict[str, int], title: str, tags: list[str]
    ) -> float:
        title_tokens = set(_keywords(title))
        tag_tokens = {t.lower() for t in tags}
        score = 0.0
        for tok in q_set:
            tf = counts.get(tok, 0)
            if tf:
                score += 1.0 + min(tf, 5) * 0.5
            if tok in title_tokens:
                score += 3.0
            if tok in tag_tokens:
                score += 2.0
        return score

    def _best_chunk(
        self, doc: _CustomerDocument, q_set: set[str]
    ) -> tuple[_CustomerChunk, str]:
        """Pick the highest-overlap chunk (for a resolvable citation) + snippet."""
        best: Optional[_CustomerChunk] = None
        best_score = -1.0
        for chunk in doc.chunks:
            score = sum(chunk._token_counts.get(tok, 0) for tok in q_set)
            if score > best_score:
                best_score = score
                best = chunk
        chunk = best or doc.chunks[0]
        snippet = " ".join(chunk.text.split())[:240]
        return chunk, snippet

    def retrieve(
        self, query: str, k: int = 3, tenant_id: Optional[str] = None
    ) -> list[DocumentRef]:
        """Return up to ``k`` documents ranked by keyword relevance to ``query``.

        Scoring: for each distinct query keyword, add its body term-frequency
        plus a boost when it appears in the document title or tags. Documents
        with zero overlap are excluded so the assistant never cites an
        irrelevant document. Keyword-based only (see module docstring).

        Tenant scoping + approval gate: the platform-seeded corpus is always
        eligible. A customer document is eligible ONLY when ``tenant_id`` matches
        its tenant AND it has been approved -- so ``retrieve`` never returns
        another tenant's chunk, and never an unapproved one.
        """
        q_tokens = _keywords(query)
        if not q_tokens:
            return []
        q_set = set(q_tokens)
        seeded_scored: list[tuple[float, _Document]] = []
        customer_scored: list[tuple[float, _CustomerDocument]] = []
        with self._lock:
            for doc in self._docs.values():
                score = self._score_tokens(q_set, doc._token_counts, doc.title, doc.tags)
                if score > 0:
                    seeded_scored.append((score, doc))
            if tenant_id is not None:
                for cust in self._customer_docs.values():
                    if cust.tenant_id != tenant_id or not cust.approved:
                        continue
                    score = self._score_tokens(
                        q_set, cust._token_counts, cust.title, cust.tags
                    )
                    if score > 0:
                        customer_scored.append((score, cust))

            scored: list[tuple[float, DocumentRef]] = []
            for score, doc in seeded_scored:
                scored.append(
                    (score, doc.to_ref(score=round(score, 3), snippet=self._snippet(doc, q_set)))
                )
            for score, cust in customer_scored:
                chunk, snippet = self._best_chunk(cust, q_set)
                scored.append(
                    (score, cust.to_ref(chunk=chunk, score=round(score, 3), snippet=snippet))
                )
        scored.sort(key=lambda item: (item[0], item[1].document_id), reverse=True)
        return [ref for _, ref in scored[: max(0, k)]]


#: Process-wide default store over the seeded corpus.
_store: DocumentStore | None = None
_store_lock = threading.RLock()


def get_store() -> DocumentStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DocumentStore()
        return _store


def list_documents(tenant_id: Optional[str] = None) -> list[DocumentRef]:
    return get_store().list(tenant_id=tenant_id)


def get_document(document_id: str, tenant_id: Optional[str] = None) -> dict | None:
    return get_store().get(document_id, tenant_id=tenant_id)


def retrieve(query: str, k: int = 3, tenant_id: Optional[str] = None) -> list[DocumentRef]:
    """Keyword-retrieve up to ``k`` documents relevant to ``query``.

    Includes the platform-seeded corpus plus, when ``tenant_id`` is supplied, that
    tenant's approved customer documents (never another tenant's, never
    unapproved).
    """
    return get_store().retrieve(query, k, tenant_id=tenant_id)
