"""Tests for structure-aware chunking and relationship preservation
(``ingestion/chunker.py``).
"""
from __future__ import annotations

from ingestion.chunker import chunk_document


def test_small_document_becomes_single_chunk():
    document = {"service": "pets", "endpoint": "/pets"}
    chunks = chunk_document(document, "doc-1", max_chars=1800)
    assert len(chunks) == 1
    assert chunks[0]["parent_chunk_id"] is None
    assert chunks[0]["document_id"] == "doc-1"
    assert chunks[0]["kind"] == "object"


def test_large_document_produces_multiple_related_chunks():
    # A document too large to fit in one chunk must be split while preserving
    # the ability to reconstruct the parent/child relationship.
    document = {
        "service": "pets",
        "endpoints": {
            f"endpoint_{i}": {
                "path": f"/pets/{i}",
                "method": "GET",
                "description": "x" * 50,
            }
            for i in range(50)
        },
    }
    chunks = chunk_document(document, "doc-2", max_chars=200, overlap_chars=20)
    assert len(chunks) > 1

    chunk_ids = {c["chunk_id"] for c in chunks}
    # Every chunk id must be unique (required to disambiguate reconstruction).
    assert len(chunk_ids) == len(chunks)

    # Any declared parent must itself be a known chunk in the same document,
    # so a retrieved child chunk can always be traced back to its parent.
    for chunk in chunks:
        assert chunk["document_id"] == "doc-2"
        if chunk["parent_chunk_id"] is not None:
            assert chunk["parent_chunk_id"] in chunk_ids
        assert chunk["path"].startswith("$")


def test_chunks_carry_path_metadata_for_reconstruction():
    document = {"a": {"b": {"c": "value"}}}
    chunks = chunk_document(document, "doc-3", max_chars=5)
    paths = [c["path"] for c in chunks]
    # The nested path down to the leaf value must be observable in the metadata.
    assert any("a" in p and "b" in p and "c" in p for p in paths)
