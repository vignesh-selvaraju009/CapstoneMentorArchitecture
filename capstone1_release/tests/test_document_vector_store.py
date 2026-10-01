"""Tests for the configurable embedding/vector-store abstraction
(``ingestion/document_vector_store.py``).

Uses the ``fake_sentence_transformer`` fixture so tests run fully offline and
deterministically, without downloading real embedding model weights.
"""
from __future__ import annotations

import pytest

from ingestion.chunker import chunk_document
from ingestion.document_vector_store import DocumentVectorStore


def _sample_chunks():
    document = {
        "service": "pets",
        "endpoint": "/pets/{id}",
        "method": "GET",
        "description": "Retrieve a single pet by its identifier",
    }
    return chunk_document(document, "doc-1", max_chars=40, overlap_chars=5)


def test_build_requires_chunks(fake_sentence_transformer, tmp_path):
    store = DocumentVectorStore(index_path=tmp_path / "idx.faiss")
    with pytest.raises(ValueError):
        store.build([])


def test_build_save_load_query_roundtrip(fake_sentence_transformer, tmp_path):
    chunks = _sample_chunks()
    store = DocumentVectorStore(index_path=tmp_path / "idx.faiss")
    store.build(chunks)
    store.save()

    assert (tmp_path / "idx.faiss").exists()
    assert (tmp_path / "idx.meta.json").exists()

    reloaded = DocumentVectorStore(index_path=tmp_path / "idx.faiss")
    reloaded.load()
    results = reloaded.query("pet identifier", top_k=2)

    assert len(results) <= 2
    assert len(results) > 0
    # Retrieved chunks must retain relationship/reconstruction metadata.
    for result in results:
        assert "chunk_id" in result
        assert "document_id" in result
        assert "score" in result


def test_query_without_prior_load_or_build_raises(tmp_path, fake_sentence_transformer):
    store = DocumentVectorStore(index_path=tmp_path / "missing.faiss")
    with pytest.raises(FileNotFoundError):
        store.query("anything")


def test_embedding_model_is_configuration_driven(fake_sentence_transformer, tmp_path):
    store = DocumentVectorStore(index_path=tmp_path / "idx.faiss")
    from ingestion.document_parser import load_ingestion_config

    assert store.model_name == load_ingestion_config()["embedding"]["model"]


def test_embedding_model_is_reused_across_store_instances(fake_sentence_transformer):
    first_store = DocumentVectorStore()
    second_store = DocumentVectorStore()

    first_store._embed(["first endpoint"])
    second_store._embed(["second endpoint"])

    assert first_store.model is second_store.model
