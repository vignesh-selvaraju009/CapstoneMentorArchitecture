"""FAISS-backed retrieval over the knowledge base (test patterns, security rules,
boundary values).

Builds a single vector index over all knowledge-base entries (each entry becomes
one embedded document: its title + description/owasp text), persists it to disk,
and exposes a similarity-search API used by ``llm/prompt_builder.py`` to retrieve
the most relevant patterns/rules/boundary values for a given endpoint summary.

No UI code lives here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import faiss
import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from config import settings
from utils.helpers import get_logger, read_json

logger = get_logger(__name__)


@dataclass
class KnowledgeEntry:
    """One retrievable unit from the knowledge base."""

    id: str
    source: str  # "test_patterns" | "security_rules" | "boundary_values"
    category: str
    title: str
    text: str  # the text that was embedded (used for the LLM prompt context)
    metadata: dict[str, Any] = field(default_factory=dict)


def _entries_from_test_patterns(data: dict[str, Any]) -> list[KnowledgeEntry]:
    entries = []
    for item in data.get("patterns", []):
        text = f"{item.get('title', '')}. {item.get('description', '')}".strip()
        entries.append(
            KnowledgeEntry(
                id=item.get("id", ""),
                source="test_patterns",
                category=item.get("category", "Uncategorized"),
                title=item.get("title", ""),
                text=text,
                metadata={"methods": item.get("methods", [])},
            )
        )
    return entries


def _entries_from_security_rules(data: dict[str, Any]) -> list[KnowledgeEntry]:
    entries = []
    for item in data.get("rules", []):
        text = f"{item.get('title', '')}. {item.get('description', '')} ({item.get('owasp', '')})".strip()
        entries.append(
            KnowledgeEntry(
                id=item.get("id", ""),
                source="security_rules",
                category=item.get("category", "Security"),
                title=item.get("title", ""),
                text=text,
                metadata={"owasp": item.get("owasp", "")},
            )
        )
    return entries


def _entries_from_boundary_values(data: dict[str, Any]) -> list[KnowledgeEntry]:
    entries = []
    for type_name, spec in data.get("boundary_values", {}).items():
        description = spec.get("description", "")
        text = f"Boundary values for {type_name} fields. {description}".strip()
        entries.append(
            KnowledgeEntry(
                id=f"boundary-{type_name}",
                source="boundary_values",
                category="Boundary",
                title=f"Boundary values: {type_name}",
                text=text,
                metadata={"type": type_name, **{k: v for k, v in spec.items() if k != "description"}},
            )
        )
    return entries


def load_knowledge_entries() -> list[KnowledgeEntry]:
    """Load and flatten all knowledge-base JSON files into embeddable entries."""
    entries: list[KnowledgeEntry] = []
    entries += _entries_from_test_patterns(read_json(settings.test_patterns_file, default={}))
    entries += _entries_from_security_rules(read_json(settings.security_rules_file, default={}))
    entries += _entries_from_boundary_values(read_json(settings.boundary_values_file, default={}))
    logger.info("Loaded %d knowledge base entries", len(entries))
    return entries


class VectorStore:
    """Wraps a FAISS flat index (cosine similarity via normalized inner product)
    over :class:`KnowledgeEntry` embeddings produced by a sentence-transformers model.
    """

    def __init__(self, embedding_model: str | None = None, index_path: Path | None = None):
        self._model_name = embedding_model or settings.embedding_model
        self._index_path = index_path or settings.faiss_index_path
        self._model: SentenceTransformer | None = None
        self._index: faiss.Index | None = None
        self._entries: list[KnowledgeEntry] = []

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model '%s'", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        vectors = vectors.astype("float32")
        faiss.normalize_L2(vectors)
        return vectors

    def build_index(self, entries: list[KnowledgeEntry] | None = None) -> None:
        """Build the FAISS index in memory from knowledge base entries (or ``entries``)."""
        self._entries = entries if entries is not None else load_knowledge_entries()
        if not self._entries:
            raise ValueError("No knowledge base entries to index")

        vectors = self._embed([entry.text for entry in self._entries])
        dimension = vectors.shape[1]
        index = faiss.IndexFlatIP(dimension)
        index.add(vectors)
        self._index = index
        logger.info("Built FAISS index with %d vectors (dim=%d)", index.ntotal, dimension)

    def save_index(self, path: Path | None = None) -> None:
        """Persist the FAISS index and its entry metadata to disk."""
        if self._index is None:
            raise RuntimeError("Index has not been built yet; call build_index() first")
        target = path or self._index_path
        target.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(target))
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump([entry.__dict__ for entry in self._entries], handle, indent=2)
        logger.info("Saved FAISS index to %s (metadata: %s)", target, metadata_path)

    def load_index(self, path: Path | None = None) -> None:
        """Load a previously saved FAISS index and its entry metadata from disk."""
        source = path or self._index_path
        metadata_path = source.with_suffix(source.suffix + ".meta.json")
        if not source.exists() or not metadata_path.exists():
            raise FileNotFoundError(f"No saved index found at {source} / {metadata_path}")

        self._index = faiss.read_index(str(source))
        with metadata_path.open("r", encoding="utf-8") as handle:
            raw_entries = json.load(handle)
        self._entries = [KnowledgeEntry(**raw) for raw in raw_entries]
        logger.info("Loaded FAISS index from %s (%d entries)", source, len(self._entries))

    def ensure_ready(self) -> None:
        """Load the index from disk if available, otherwise build and save a fresh one."""
        try:
            self.load_index()
        except FileNotFoundError:
            logger.info("No persisted index found; building a fresh one")
            self.build_index()
            self.save_index()

    def query(self, text: str, top_k: int = 5, category: str | None = None) -> list[KnowledgeEntry]:
        """Return the ``top_k`` most relevant knowledge entries for ``text``.

        Args:
            text: The endpoint summary (or any free text) to search with.
            top_k: Maximum number of entries to return.
            category: If given, restrict results to entries with this exact
                ``category`` (e.g. "Security", "Boundary").
        """
        if self._index is None:
            raise RuntimeError("Index is not loaded; call ensure_ready()/build_index() first")

        query_vector = self._embed([text])
        # Over-fetch when filtering by category so we still return top_k after filtering.
        search_k = top_k * 4 if category else top_k
        search_k = min(search_k, self._index.ntotal) or 1
        scores, indices = self._index.search(query_vector, search_k)

        results: list[KnowledgeEntry] = []
        for idx in indices[0]:
            if idx < 0 or idx >= len(self._entries):
                continue
            entry = self._entries[idx]
            if category and entry.category != category:
                continue
            results.append(entry)
            if len(results) >= top_k:
                break
        return results
