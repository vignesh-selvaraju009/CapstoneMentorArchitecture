"""Run a Postman collection with Newman (Node.js CLI) and capture structured
results.

Gracefully reports (rather than raising) when the ``newman`` executable is not
found on PATH, since Newman is an optional external dependency (Node.js).

No UI code lives here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from utils.helpers import get_logger

logger = get_logger(__name__)


@dataclass
class NewmanAssertionResult:
    """Outcome of a single Postman test assertion (``pm.test(...)``)."""

    name: str
    passed: bool
    error_message: str | None = None


@dataclass
class NewmanRequestResult:
    """Outcome of a single request/item run by Newman."""

    name: str
    status_code: int | None
    response_time_ms: float | None
    assertions: list[NewmanAssertionResult] = field(default_factory=list)


@dataclass
class NewmanRunResult:
    """Aggregate result of one Newman invocation."""

    available: bool
    exit_code: int | None
    total_requests: int
    total_assertions: int
    failed_assertions: int
    requests: list[NewmanRequestResult] = field(default_factory=list)
    json_report_path: Path | None = None
    error: str | None = None

    @property
    def all_passed(self) -> bool:
        return self.available and self.failed_assertions == 0 and self.exit_code == 0


def is_newman_available(executable: str | None = None) -> bool:
    """Return True if the Newman CLI can be found on PATH."""
    return shutil.which(executable or settings.newman_executable) is not None


def _parse_newman_json_report(report: dict) -> NewmanRunResult:
    run = report.get("run", {})
    executions = run.get("executions", [])

    requests: list[NewmanRequestResult] = []
    total_assertions = 0
    failed_assertions = 0

    for execution in executions:
        item_name = execution.get("item", {}).get("name", "unknown")
        response = execution.get("response") or {}
        status_code = response.get("code")
        response_time = response.get("responseTime")

        assertions: list[NewmanAssertionResult] = []
        for assertion in execution.get("assertions", []):
            total_assertions += 1
            error = assertion.get("error")
            passed = error is None
            if not passed:
                failed_assertions += 1
            assertions.append(
                NewmanAssertionResult(
                    name=assertion.get("assertion", "unknown assertion"),
                    passed=passed,
                    error_message=(error or {}).get("message") if error else None,
                )
            )

        requests.append(
            NewmanRequestResult(
                name=item_name,
                status_code=status_code,
                response_time_ms=response_time,
                assertions=assertions,
            )
        )

    return NewmanRunResult(
        available=True,
        exit_code=run.get("stats", {}).get("requests", {}).get("failed", 0) and 1 or 0,
        total_requests=len(requests),
        total_assertions=total_assertions,
        failed_assertions=failed_assertions,
        requests=requests,
    )


def run_newman(
    collection_path: Path | None = None,
    json_report_path: Path | None = None,
    executable: str | None = None,
) -> NewmanRunResult:
    """Run ``newman run <collection>`` and return structured results.

    Args:
        collection_path: Path to the Postman collection JSON; defaults to
            ``settings.generated_postman_dir / "collection.json"``.
        json_report_path: Where Newman should write its JSON report; defaults to
            ``settings.reports_dir / "newman_report.json"``.
        executable: Override the ``newman`` executable name/path (defaults to
            ``settings.newman_executable``).

    Returns:
        A :class:`NewmanRunResult`. If Newman is not installed, ``available`` is
        False and ``error`` describes the problem; this is not raised as an
        exception so callers can degrade gracefully (e.g. show a warning in the UI).
    """
    executable = executable or settings.newman_executable
    collection_path = collection_path or (settings.generated_postman_dir / "collection.json")
    json_report_path = json_report_path or (settings.reports_dir / "newman_report.json")
    json_report_path.parent.mkdir(parents=True, exist_ok=True)

    if not is_newman_available(executable):
        message = (
            f"Newman executable '{executable}' not found on PATH. "
            "Install Node.js and run `npm install -g newman` to enable Postman collection execution."
        )
        logger.warning(message)
        return NewmanRunResult(
            available=False,
            exit_code=None,
            total_requests=0,
            total_assertions=0,
            failed_assertions=0,
            error=message,
        )

    if not collection_path.exists():
        message = f"Postman collection not found at {collection_path}"
        logger.error(message)
        return NewmanRunResult(
            available=True,
            exit_code=None,
            total_requests=0,
            total_assertions=0,
            failed_assertions=0,
            error=message,
        )

    command = [
        executable,
        "run",
        str(collection_path),
        "--reporters",
        "cli,json",
        "--reporter-json-export",
        str(json_report_path),
    ]

    logger.info("Running Newman: %s", " ".join(command))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    except (subprocess.SubprocessError, OSError) as exc:
        message = f"Failed to execute Newman: {exc}"
        logger.error(message)
        return NewmanRunResult(
            available=True,
            exit_code=None,
            total_requests=0,
            total_assertions=0,
            failed_assertions=0,
            error=message,
        )

    if completed.returncode not in (0, 1):
        # 0 = all assertions passed, 1 = some assertions failed (still a valid run).
        logger.warning("Newman exited with unexpected code %d: %s", completed.returncode, completed.stderr)

    if not json_report_path.exists():
        message = f"Newman did not produce a JSON report at {json_report_path}: {completed.stderr}"
        logger.error(message)
        return NewmanRunResult(
            available=True,
            exit_code=completed.returncode,
            total_requests=0,
            total_assertions=0,
            failed_assertions=0,
            error=message,
        )

    with json_report_path.open("r", encoding="utf-8") as handle:
        report_data = json.load(handle)

    result = _parse_newman_json_report(report_data)
    result.exit_code = completed.returncode
    result.json_report_path = json_report_path
    logger.info(
        "Newman run complete: %d request(s), %d assertion(s), %d failed (exit=%d)",
        result.total_requests, result.total_assertions, result.failed_assertions, completed.returncode,
    )
    return result
