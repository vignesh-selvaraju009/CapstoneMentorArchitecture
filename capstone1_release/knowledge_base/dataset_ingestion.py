"""Ingestion of user-uploaded test-case datasets into the knowledge base.

The uploaded dataset is a single JSON array of flat "test case record" objects.
Each record carries a ``kb_type`` field that routes it to one of the four
knowledge base blocks (see ``knowledge_base/vector_store.py`` for how these are
later embedded/retrieved):

- ``test_pattern``        -> knowledge_base/test_patterns.json ("patterns")
- ``security_rule``       -> knowledge_base/security_rules.json ("rules")
- ``boundary_value``      -> knowledge_base/boundary_values.json ("boundary_values")
- ``historical_feedback`` -> knowledge_base/historical_feedback.json

Records are upserted by ``id`` (or assigned a generated id) so re-ingesting the
same dataset does not create duplicates. No UI code lives here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import settings
from utils.helpers import get_logger, read_json, write_json

logger = get_logger(__name__)

VALID_KB_TYPES = ("test_pattern", "security_rule", "boundary_value", "historical_feedback")
VALID_FEEDBACK_ACTIONS = ("approved", "rejected", "modified")


@dataclass
class IngestSummary:
    """Result of ingesting one dataset upload."""

    total: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {kb_type: 0 for kb_type in VALID_KB_TYPES})
    errors: list[str] = field(default_factory=list)


def _upsert_by_id(existing: list[dict[str, Any]], record_id: str, new_item: dict[str, Any]) -> None:
    for i, item in enumerate(existing):
        if item.get("id") == record_id:
            existing[i] = new_item
            return
    existing.append(new_item)


def _ingest_test_pattern(record: dict[str, Any]) -> None:
    data = read_json(settings.test_patterns_file, default={"patterns": []})
    record_id = record.get("id") or f"custom-{uuid.uuid4().hex[:8]}"
    item = {
        "id": record_id,
        "category": record.get("category", "Uncategorized"),
        "methods": record.get("methods", []),
        "title": record.get("title", ""),
        "description": record.get("description", ""),
    }
    _upsert_by_id(data.setdefault("patterns", []), record_id, item)
    write_json(settings.test_patterns_file, data)


def _ingest_security_rule(record: dict[str, Any]) -> None:
    data = read_json(settings.security_rules_file, default={"rules": []})
    record_id = record.get("id") or f"custom-{uuid.uuid4().hex[:8]}"
    item = {
        "id": record_id,
        "category": record.get("category", "Security"),
        "owasp": record.get("owasp", ""),
        "title": record.get("title", ""),
        "description": record.get("description", ""),
    }
    _upsert_by_id(data.setdefault("rules", []), record_id, item)
    write_json(settings.security_rules_file, data)


def _ingest_boundary_value(record: dict[str, Any]) -> None:
    type_name = record.get("type_name")
    if not type_name:
        raise ValueError("boundary_value record requires a 'type_name' field")
    data = read_json(settings.boundary_values_file, default={"boundary_values": {}})
    spec: dict[str, Any] = {"description": record.get("description", "")}
    if "values" in record:
        spec["values"] = record["values"]
    if "cases" in record:
        spec["cases"] = record["cases"]
    data.setdefault("boundary_values", {})[type_name] = spec
    write_json(settings.boundary_values_file, data)


def _ingest_historical_feedback(record: dict[str, Any]) -> None:
    action = record.get("action")
    if action not in VALID_FEEDBACK_ACTIONS:
        raise ValueError(f"historical_feedback record requires 'action' in {VALID_FEEDBACK_ACTIONS}")
    data = read_json(
        settings.historical_feedback_file,
        default={"approved": [], "rejected": [], "modified": []},
    )
    entry = {
        "title": record.get("title", ""),
        "description": record.get("description", ""),
        "priority": record.get("priority", "Medium"),
        "category": record.get("category", "Uncategorized"),
        "expected_status": record.get("expected_status"),
        "expected_response": record.get("expected_response", ""),
        "assertions": record.get("assertions", []),
        "notes": record.get("notes"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    data.setdefault(action, []).append(entry)
    write_json(settings.historical_feedback_file, data)


_HANDLERS = {
    "test_pattern": _ingest_test_pattern,
    "security_rule": _ingest_security_rule,
    "boundary_value": _ingest_boundary_value,
    "historical_feedback": _ingest_historical_feedback,
}


def ingest_dataset(records: list[dict[str, Any]]) -> IngestSummary:
    """Classify and merge each record in ``records`` into the knowledge base.

    Returns an :class:`IngestSummary` with per-block counts and any per-record
    validation errors (invalid records are skipped, not raised).
    """
    summary = IngestSummary()
    for i, record in enumerate(records):
        kb_type = record.get("kb_type")
        if kb_type not in VALID_KB_TYPES:
            summary.errors.append(f"Record {i}: missing/invalid 'kb_type' (must be one of {VALID_KB_TYPES})")
            continue
        try:
            _HANDLERS[kb_type](record)
        except (ValueError, KeyError) as exc:
            summary.errors.append(f"Record {i} ({kb_type}): {exc}")
            continue
        summary.counts[kb_type] += 1
        summary.total += 1

    logger.info(
        "Ingested dataset: %d record(s) accepted (%s), %d error(s)",
        summary.total, summary.counts, len(summary.errors),
    )
    return summary


def knowledge_base_counts() -> dict[str, int]:
    """Return current entry counts per knowledge base block, for display in the UI."""
    patterns = read_json(settings.test_patterns_file, default={"patterns": []})
    rules = read_json(settings.security_rules_file, default={"rules": []})
    boundary = read_json(settings.boundary_values_file, default={"boundary_values": {}})
    feedback = read_json(
        settings.historical_feedback_file, default={"approved": [], "rejected": [], "modified": []}
    )
    return {
        "test_pattern": len(patterns.get("patterns", [])),
        "security_rule": len(rules.get("rules", [])),
        "boundary_value": len(boundary.get("boundary_values", {})),
        "historical_feedback": sum(len(v) for v in feedback.values()),
    }
