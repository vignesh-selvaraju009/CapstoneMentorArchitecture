"""Tests for the generic, format-independent document parser/classifier
(``ingestion/document_parser.py``).
"""
from __future__ import annotations

import json

import pytest

from ingestion.document_parser import classify_document, load_ingestion_config, parse_file


def test_load_ingestion_config_is_configuration_driven():
    cfg = load_ingestion_config()
    assert "accepted_extensions" in cfg
    assert "parsers" in cfg
    assert "classification" in cfg
    assert "common_document_model" in cfg
    # No document type / format is hardcoded: it all comes from this file.
    assert ".json" in cfg["accepted_extensions"]
    assert ".yaml" in cfg["accepted_extensions"]


def test_parse_file_json(tmp_path):
    path = tmp_path / "doc.json"
    path.write_text(json.dumps({"a": 1, "b": "text"}), encoding="utf-8")
    result = parse_file(str(path))
    assert result == {"a": 1, "b": "text"}


def test_parse_file_yaml(tmp_path):
    path = tmp_path / "doc.yaml"
    path.write_text("a: 1\nb: text\n", encoding="utf-8")
    result = parse_file(str(path))
    assert result == {"a": 1, "b": "text"}


def test_parse_file_xml(tmp_path):
    path = tmp_path / "doc.xml"
    path.write_text("<root><endpoint>/pets</endpoint></root>", encoding="utf-8")
    result = parse_file(str(path))
    assert "root" in result
    assert result["root"]["endpoint"] == "/pets"


def test_parse_file_text(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("some backend knowledge document", encoding="utf-8")
    result = parse_file(str(path))
    assert result == "some backend knowledge document"


def test_parse_file_unsupported_extension(tmp_path):
    path = tmp_path / "doc.exe"
    path.write_bytes(b"\x00\x01")
    with pytest.raises(ValueError):
        parse_file(str(path))


@pytest.mark.parametrize(
    "document,extension,expected",
    [
        ({"openapi": "3.0.3", "paths": {}}, ".yaml", "api_specification"),
        ({"swagger": "2.0"}, ".json", "api_specification"),
        ({"test_case": "x", "expected_status": 200, "assertions": []}, ".json", "test_knowledge"),
        ({"endpoint": "/x", "request": {}, "response": {}}, ".json", "backend_document"),
        ({"nothing": "recognizable"}, ".json", "backend_document"),
    ],
)
def test_classify_document_uses_configured_rules(document, extension, expected):
    assert classify_document(document, extension) == expected


def test_classify_document_works_on_text_documents():
    # Format-independent: classification must also work on plain-text documents.
    assert classify_document("This document describes an OpenAPI paths section", ".txt") == "api_specification"
