"""Regression tests for the existing OpenAPI/Swagger parser
(``parser/openapi_parser.py``), which must continue to work unchanged.
"""
from __future__ import annotations

from parser.openapi_parser import parse_spec


def test_parse_petstore_spec(petstore_spec_path):
    spec = parse_spec(str(petstore_spec_path))

    assert spec.title == "Swagger Petstore - Sample"
    assert spec.version == "1.0.0"
    assert spec.base_url == "https://petstore.example.com/v1"
    assert len(spec.endpoints) > 0
    assert {e.method for e in spec.endpoints} <= {"GET", "POST", "PUT", "DELETE", "PATCH"}


def test_endpoint_auth_is_extracted(petstore_spec_path):
    spec = parse_spec(str(petstore_spec_path))
    assert any(endpoint.auth for endpoint in spec.endpoints)


def test_endpoint_parameters_have_locations(petstore_spec_path):
    spec = parse_spec(str(petstore_spec_path))
    all_locations = {p.location for e in spec.endpoints for p in e.parameters}
    assert all_locations <= {"path", "query", "header", "cookie"}
