"""Regression tests for the legacy dataset ingestion flow
(``knowledge_base/dataset_ingestion.py``), which must keep working alongside
the new generic document-ingestion pipeline.
"""
from __future__ import annotations

import pytest

from knowledge_base import dataset_ingestion as di


@pytest.fixture(autouse=True)
def _isolated_kb_files(monkeypatch, tmp_path):
    import dataclasses

    from config import settings as global_settings

    # Settings is a frozen dataclass; build an isolated copy instead of mutating it.
    isolated = dataclasses.replace(
        global_settings,
        test_patterns_file=tmp_path / "test_patterns.json",
        security_rules_file=tmp_path / "security_rules.json",
        boundary_values_file=tmp_path / "boundary_values.json",
        historical_feedback_file=tmp_path / "historical_feedback.json",
    )
    monkeypatch.setattr(di, "settings", isolated)


def test_ingest_dataset_routes_records_by_kb_type():
    records = [
        {"kb_type": "test_pattern", "id": "tp-1", "title": "t", "description": "d"},
        {"kb_type": "security_rule", "id": "sr-1", "title": "t", "description": "d", "owasp": "A01"},
        {"kb_type": "boundary_value", "type_name": "string", "description": "d", "values": ["", "a"]},
        {"kb_type": "historical_feedback", "action": "approved", "title": "t"},
    ]
    summary = di.ingest_dataset(records)

    assert summary.total == 4
    assert summary.errors == []
    assert summary.counts["test_pattern"] == 1
    assert summary.counts["security_rule"] == 1
    assert summary.counts["boundary_value"] == 1
    assert summary.counts["historical_feedback"] == 1


def test_ingest_dataset_reports_errors_for_invalid_records():
    records = [
        {"kb_type": "unknown_type"},
        {"kb_type": "boundary_value"},  # missing required type_name
    ]
    summary = di.ingest_dataset(records)
    assert summary.total == 0
    assert len(summary.errors) == 2


def test_knowledge_base_counts_reflects_ingested_records():
    di.ingest_dataset([{"kb_type": "test_pattern", "id": "tp-1", "title": "t", "description": "d"}])
    counts = di.knowledge_base_counts()
    assert counts["test_pattern"] == 1
