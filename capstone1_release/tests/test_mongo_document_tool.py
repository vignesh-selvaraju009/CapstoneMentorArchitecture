"""Tests for the MongoDB document-understanding tool
(``ingestion/mongo_document_tool.py``), backed by ``mongomock`` so no real
MongoDB server is required.
"""
from __future__ import annotations

import pytest

from ingestion.chunker import chunk_document
from ingestion.common_model import normalize_generic


def test_ping(mongo_repository):
    assert mongo_repository.ping() is True


def test_save_and_get_document(mongo_repository):
    document_id = "doc-1"
    raw = {"endpoint": "/pets", "method": "GET"}
    normalized = normalize_generic(raw, document_id, "backend_document")

    mongo_repository.save_document(
        document_id, "pets.json", "backend_document", raw, normalized, "backend_document"
    )
    stored = mongo_repository.get_document(document_id)

    assert stored is not None
    assert stored["document_id"] == document_id
    assert stored["file_name"] == "pets.json"
    assert stored["normalized"] == normalized
    assert "_id" not in stored


def test_save_document_upserts(mongo_repository):
    document_id = "doc-2"
    mongo_repository.save_document(document_id, "v1.json", "t", {"a": 1}, {}, "t")
    mongo_repository.save_document(document_id, "v2.json", "t", {"a": 2}, {}, "t")

    stored = mongo_repository.get_document(document_id)
    assert stored["file_name"] == "v2.json"
    assert mongo_repository.collection.count_documents({"document_id": document_id}) == 1


def test_save_and_get_chunks(mongo_repository):
    document_id = "doc-3"
    document = {"service": "pets", "endpoint": "/pets", "method": "GET"}
    chunks = chunk_document(document, document_id, max_chars=10, overlap_chars=2)
    assert len(chunks) > 1

    mongo_repository.save_chunks(chunks)
    stored_chunks = mongo_repository.get_chunks(document_id)

    assert len(stored_chunks) == len(chunks)
    assert {c["chunk_id"] for c in stored_chunks} == {c["chunk_id"] for c in chunks}


def test_save_chunks_replaces_previous_chunks_for_same_document(mongo_repository):
    document_id = "doc-4"
    first = chunk_document({"a": "x" * 50}, document_id, max_chars=10)
    mongo_repository.save_chunks(first)
    second = chunk_document({"b": "y" * 50}, document_id, max_chars=10)
    mongo_repository.save_chunks(second)

    stored = mongo_repository.get_chunks(document_id)
    assert {c["chunk_id"] for c in stored} == {c["chunk_id"] for c in second}


def test_get_all_chunks_spans_documents(mongo_repository):
    mongo_repository.save_chunks(chunk_document({"a": 1}, "doc-a", max_chars=1800))
    mongo_repository.save_chunks(chunk_document({"b": 2}, "doc-b", max_chars=1800))
    all_chunks = mongo_repository.get_all_chunks()
    document_ids = {c["document_id"] for c in all_chunks}
    assert document_ids == {"doc-a", "doc-b"}


def test_document_understanding_tool_reconstructs_common_model_and_chunks(mongo_repository):
    from ingestion.mongo_document_tool import DocumentUnderstandingTool

    document_id = "doc-5"
    raw = {"endpoint": "/orders", "method": "POST", "required": ["id"]}
    normalized = normalize_generic(raw, document_id, "backend_document")
    mongo_repository.save_document(document_id, "orders.json", "backend_document", raw, normalized, "backend_document")
    mongo_repository.save_chunks(chunk_document(raw, document_id, max_chars=10, overlap_chars=2))

    tool = DocumentUnderstandingTool(mongo_repository)
    result = tool.understand(document_id)

    assert result["document_id"] == document_id
    assert result["common_parameters"] == normalized
    assert len(result["chunks"]) > 0


def test_document_understanding_tool_raises_for_unknown_document(mongo_repository):
    from ingestion.mongo_document_tool import DocumentUnderstandingTool

    with pytest.raises(KeyError):
        DocumentUnderstandingTool(mongo_repository).understand("does-not-exist")


def test_repository_uses_local_store_without_mongo_uri(monkeypatch, tmp_path):
    import dataclasses

    from config import settings as global_settings
    from ingestion import mongo_document_tool
    from ingestion.mongo_document_tool import MongoDocumentRepository

    isolated = dataclasses.replace(global_settings, mongo_uri="")
    monkeypatch.setattr(mongo_document_tool, "settings", isolated)
    monkeypatch.setattr(
        mongo_document_tool, "LOCAL_DOCUMENT_STORE_PATH", tmp_path / "documents.sqlite3"
    )

    repository = MongoDocumentRepository()
    assert repository.ping() is True
    repository.save_document("doc-local", "pets.yaml", "api_specification", {}, {}, "api_specification")
    repository.save_chunks([{"chunk_id": "chunk-local", "document_id": "doc-local", "text": "pets"}])

    reloaded = MongoDocumentRepository()
    assert reloaded.get_document("doc-local")["file_name"] == "pets.yaml"
    assert reloaded.get_chunks("doc-local")[0]["text"] == "pets"


def test_repository_falls_back_when_mongo_is_unreachable(monkeypatch, tmp_path):
    import dataclasses

    from config import settings as global_settings
    from ingestion import mongo_document_tool
    from ingestion.mongo_document_tool import MongoDocumentRepository
    from pymongo.errors import ServerSelectionTimeoutError

    class UnavailableMongoClient:
        def __init__(self, *_args, **_kwargs):
            self.admin = self

        def __getitem__(self, _name):
            return self

        def command(self, _command):
            raise ServerSelectionTimeoutError("connection refused")

    isolated = dataclasses.replace(global_settings, mongo_uri="mongodb://localhost:27017")
    monkeypatch.setattr(mongo_document_tool, "settings", isolated)
    monkeypatch.setattr(mongo_document_tool, "MongoClient", UnavailableMongoClient)
    monkeypatch.setattr(
        mongo_document_tool, "LOCAL_DOCUMENT_STORE_PATH", tmp_path / "documents.sqlite3"
    )

    repository = MongoDocumentRepository()
    assert repository.ping() is True
    repository.save_document("doc-offline", "pets.yaml", "api_specification", {}, {}, "api_specification")

    assert repository.get_document("doc-offline")["file_name"] == "pets.yaml"
