"""Local JSON-file storage for run history: executions, generated tests,
coverage reports, run reports, and QA feedback.

Replaces the MongoDB-backed storage originally sketched in the project brief
(``storage/mongo_storage.py``) since the user opted for local JSON storage with
no external database dependency. Each record is appended to a JSON array file
under ``settings.storage_dir``, keyed by an auto-generated run id.

No UI code lives here.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from utils.helpers import get_logger, read_json, write_json

logger = get_logger(__name__)

EXECUTIONS_FILE = "executions.json"
GENERATED_TESTS_FILE = "generated_tests.json"
COVERAGE_FILE = "coverage.json"
REPORTS_FILE = "reports.json"
UI_SETTINGS_FILE = "ui_settings.json"
DATASET_UPLOADS_FILE = "dataset_uploads.json"


def _to_serializable(value: Any) -> Any:
    """Recursively convert dataclasses (and containers of them) to plain dicts/lists."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _to_serializable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _new_record(spec_name: str, data: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "spec_name": spec_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": _to_serializable(data),
    }


class JSONStorage:
    """Append-only JSON-file storage for the application's run history."""

    def __init__(self, storage_dir: Path | None = None):
        self._storage_dir = storage_dir or settings.storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, filename: str) -> Path:
        return self._storage_dir / filename

    def _append(self, filename: str, record: dict[str, Any]) -> str:
        path = self._file_path(filename)
        records: list[dict[str, Any]] = read_json(path, default=[])
        records.append(record)
        write_json(path, records)
        logger.info("Appended record %s to %s", record["id"], path)
        return record["id"]

    def _query(
        self, filename: str, spec_name: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        path = self._file_path(filename)
        records: list[dict[str, Any]] = read_json(path, default=[])
        if spec_name is not None:
            records = [r for r in records if r.get("spec_name") == spec_name]
        records = sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)
        if limit is not None:
            records = records[:limit]
        return records

    def _get(self, filename: str, record_id: str) -> dict[str, Any] | None:
        records: list[dict[str, Any]] = read_json(self._file_path(filename), default=[])
        return next((r for r in records if r.get("id") == record_id), None)

    # --- Executions (pytest + newman run results) ---

    def save_execution(self, spec_name: str, execution_data: Any) -> str:
        return self._append(EXECUTIONS_FILE, _new_record(spec_name, execution_data))

    def get_executions(self, spec_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return self._query(EXECUTIONS_FILE, spec_name, limit)

    def get_execution(self, record_id: str) -> dict[str, Any] | None:
        return self._get(EXECUTIONS_FILE, record_id)

    # --- Generated tests ---

    def save_generated_tests(self, spec_name: str, test_cases_data: Any) -> str:
        return self._append(GENERATED_TESTS_FILE, _new_record(spec_name, test_cases_data))

    def get_generated_tests(self, spec_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return self._query(GENERATED_TESTS_FILE, spec_name, limit)

    # --- Coverage reports ---

    def save_coverage(self, spec_name: str, coverage_data: Any) -> str:
        return self._append(COVERAGE_FILE, _new_record(spec_name, coverage_data))

    def get_coverage(self, spec_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return self._query(COVERAGE_FILE, spec_name, limit)

    # --- Aggregated run reports (report_generator output) ---

    def save_report(self, spec_name: str, report_data: Any) -> str:
        return self._append(REPORTS_FILE, _new_record(spec_name, report_data))

    def get_reports(self, spec_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return self._query(REPORTS_FILE, spec_name, limit)

    # --- QA feedback loop (knowledge_base/historical_feedback.json) ---

    def record_feedback(self, action: str, test_case: Any, notes: str | None = None) -> None:
        """Record a QA decision (approve/reject/modify) on a generated test case.

        Appends to ``knowledge_base/historical_feedback.json`` so that
        ``llm.prompt_builder.build_feedback_notes`` can steer future generations
        (see ``knowledge_base/vector_store.py`` for retrieval and
        ``llm/prompt_builder.py`` for how notes are folded into the prompt).

        Args:
            action: One of "approved", "rejected", "modified".
            test_case: The test case (dataclass or dict) the feedback applies to.
            notes: Optional free-text QA notes (e.g. what was changed and why).
        """
        if action not in ("approved", "rejected", "modified"):
            raise ValueError(f"Invalid feedback action: {action!r}")

        feedback_path = settings.historical_feedback_file
        feedback: dict[str, list[dict[str, Any]]] = read_json(
            feedback_path, default={"approved": [], "rejected": [], "modified": []}
        )
        entry = _to_serializable(test_case)
        if isinstance(entry, dict):
            entry = dict(entry)
            entry["notes"] = notes
            entry["recorded_at"] = datetime.now(timezone.utc).isoformat()
        feedback.setdefault(action, []).append(entry)
        write_json(feedback_path, feedback)
        logger.info("Recorded '%s' feedback for test case: %s", action, entry.get("title") if isinstance(entry, dict) else entry)

    def get_feedback(self) -> dict[str, list[dict[str, Any]]]:
        """Read the full historical feedback data."""
        return read_json(
            settings.historical_feedback_file, default={"approved": [], "rejected": [], "modified": []}
        )

    # --- UI settings (small persisted preferences, e.g. last-used base URL) ---

    def save_setting(self, key: str, value: Any) -> None:
        """Persist a single UI preference so it survives app restarts/new sessions."""
        path = self._file_path(UI_SETTINGS_FILE)
        current: dict[str, Any] = read_json(path, default={})
        current[key] = value
        write_json(path, current)

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Read a single persisted UI preference, falling back to ``default``."""
        current: dict[str, Any] = read_json(self._file_path(UI_SETTINGS_FILE), default={})
        return current.get(key, default)

    # --- Dataset uploads (raw document store for ingested test-case datasets) ---

    def save_dataset_upload(self, filename: str, records: Any) -> str:
        """Persist a raw uploaded dataset (list of test-case records) verbatim,
        before it is classified and merged into the knowledge base files."""
        return self._append(DATASET_UPLOADS_FILE, _new_record(filename, records))

    def get_dataset_uploads(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._query(DATASET_UPLOADS_FILE, limit=limit)


storage = JSONStorage()
