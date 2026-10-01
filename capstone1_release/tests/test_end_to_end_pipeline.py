"""End-to-end trace of a real sample OpenAPI spec through the full mentor
architecture pipeline:

upload -> parse -> classify -> MongoDB -> structure-aware chunking ->
relationship metadata -> embedding -> vector retrieval -> document
understanding -> Common Document Model -> (existing) TC-generation inputs.

Uses ``mongomock`` (no real MongoDB required) and a deterministic fake
embedding model (no network/model download required), so this test is fully
offline and reproducible while still exercising the real production code paths.
"""
from __future__ import annotations

import hashlib

from ingestion.chunker import chunk_document
from ingestion.common_model import normalize_openapi
from ingestion.document_parser import classify_document, load_ingestion_config, parse_file
from ingestion.document_vector_store import DocumentVectorStore
from ingestion.mongo_document_tool import DocumentUnderstandingTool
from parser.openapi_parser import parse_spec


def test_full_pipeline_with_real_petstore_sample(petstore_spec_path, mongo_repository, fake_sentence_transformer, tmp_path):
    source = str(petstore_spec_path)
    document_id = hashlib.sha256(petstore_spec_path.read_bytes()).hexdigest()[:24]

    # 1. Upload + format-independent parse.
    raw_document = parse_file(source)
    assert isinstance(raw_document, dict)

    # 2. Classification (configuration-driven, no hardcoded document type).
    classification = classify_document(raw_document, petstore_spec_path.suffix.lower())
    assert classification == load_ingestion_config()["classification"]["api_document_classification"]

    # 3. Existing OpenAPI parser remains authoritative for API specs.
    parsed_spec = parse_spec(source)
    assert len(parsed_spec.endpoints) > 0

    # 4. Normalize into the Common Document Model (stable keys, dynamic values).
    normalized = normalize_openapi(parsed_spec, document_id, classification)
    assert len(normalized) == len(parsed_spec.endpoints)

    # 5. Store document + structure-aware chunks in MongoDB.
    mongo_repository.save_document(
        document_id, petstore_spec_path.name, classification, raw_document, normalized, classification
    )
    chunks = chunk_document(raw_document, document_id, max_chars=300, overlap_chars=30)
    mongo_repository.save_chunks(chunks)
    assert len(chunks) > 1

    # 6. Relationship preservation: every chunk with a parent must resolve to a
    #    real chunk in the same document (reconstruction is possible).
    stored_chunks = mongo_repository.get_chunks(document_id)
    chunk_ids = {c["chunk_id"] for c in stored_chunks}
    parents_seen = 0
    for chunk in stored_chunks:
        if chunk["parent_chunk_id"] is not None:
            parents_seen += 1
            assert chunk["parent_chunk_id"] in chunk_ids
    assert parents_seen > 0, "expected at least one child chunk with a resolvable parent"

    # 7. Document understanding tool reconstructs the common parameters + chunks
    #    for this document from MongoDB alone.
    understanding = DocumentUnderstandingTool(mongo_repository).understand(document_id)
    assert understanding["common_parameters"] == normalized
    assert len(understanding["chunks"]) == len(chunks)

    # 8. Embedding + vector index build/query (configurable embedding provider).
    vector_store = DocumentVectorStore(index_path=tmp_path / "petstore.faiss")
    vector_store.build(mongo_repository.get_all_chunks())
    vector_store.save()
    retrieved = vector_store.query("get a pet by id", top_k=3)
    assert len(retrieved) > 0
    for r in retrieved:
        assert r["document_id"] == document_id
        assert r["chunk_id"] in chunk_ids

    # 9. Downstream TC-generation input is fully format-independent: every
    #    endpoint entry exposes the same stable key contract.
    for entry in normalized:
        assert entry["endpoint"] is not None
        assert entry["http_method"] is not None
        assert entry["document_type"] == classification
