"""Tests for the Common Document Model (``ingestion/common_model.py``).

These tests verify the core mentor requirement: the set of keys returned to
the downstream test-case generator is stable/static regardless of the source
document's original format, while the values are populated dynamically.
"""
from __future__ import annotations

import json

from ingestion.common_model import normalize_generic, normalize_openapi
from ingestion.document_parser import load_ingestion_config
from parser.openapi_parser import parse_spec


def test_normalize_generic_returns_all_configured_fields():
    cfg = load_ingestion_config()["common_document_model"]["fields"]
    document = {"method": "GET", "endpoint": "/pets", "description": "list pets"}
    result = normalize_generic(document, document_id="doc-1", document_type="backend_document")

    # Keys are stable/static and match configuration, not hardcoded in Python.
    assert set(result.keys()) >= set(cfg)
    assert result["document_id"] == "doc-1"
    assert result["document_type"] == "backend_document"
    # Values are dynamically populated via configured aliases.
    assert result["http_method"] == "GET"
    assert result["endpoint"] == "/pets"


def test_normalize_generic_missing_fields_are_none():
    document = {"unrelated_field": "value"}
    result = normalize_generic(document, document_id="doc-2", document_type="backend_document")
    assert result["endpoint"] is None
    assert result["authentication"] is None


def test_normalize_generic_on_arbitrary_json_dataset(samples_dir):
    # A completely different document shape (a flat test-case dataset) must still
    # map onto the exact same stable key set as any other document type.
    raw = json.loads((samples_dir / "sample_test_dataset.json").read_text(encoding="utf-8"))
    document = raw[0] if isinstance(raw, list) else raw
    cfg_fields = set(load_ingestion_config()["common_document_model"]["fields"])
    result = normalize_generic(document, document_id="doc-3", document_type="test_knowledge")
    assert set(result.keys()) >= cfg_fields


def test_normalize_openapi_produces_stable_keys_per_endpoint(petstore_spec_path):
    spec = parse_spec(str(petstore_spec_path))
    normalized = normalize_openapi(spec, document_id="doc-4", document_type="api_specification")

    assert len(normalized) == len(spec.endpoints)
    expected_keys = {
        "document_id", "document_type", "service_name", "service_description",
        "version", "base_url", "endpoint", "http_method", "operation_id",
        "summary", "description", "path_parameters", "query_parameters",
        "header_parameters", "request_body", "request_schema", "response_schema",
        "response_status", "authentication", "required_fields", "optional_fields",
        "data_type", "default_value", "allowed_values", "example_values",
        "constraints", "dependencies", "relationships", "business_rules", "extra",
    }
    for entry in normalized:
        assert set(entry.keys()) == expected_keys
        assert entry["document_id"] == "doc-4"
        assert entry["http_method"] in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE")


def test_normalize_openapi_and_generic_share_the_same_key_contract(samples_dir, petstore_spec_path):
    """The whole point of the common model: TC generation doesn't care whether the
    source was an OpenAPI spec or a generic backend document."""
    spec = parse_spec(str(petstore_spec_path))
    openapi_entries = normalize_openapi(spec, document_id="doc-5", document_type="api_specification")

    generic_doc = json.loads((samples_dir / "common_data_ingestion.json").read_text(encoding="utf-8"))
    if isinstance(generic_doc, list):
        generic_doc = generic_doc[0]
    generic_entry = normalize_generic(generic_doc, document_id="doc-6", document_type="backend_document")

    openapi_keys = set(openapi_entries[0].keys()) - {"extra"}
    generic_keys = set(generic_entry.keys())
    assert openapi_keys.issubset(generic_keys)
