"""Programmatically run pytest against ``generated_tests/`` (or a subset of
files), with ``pytest-html`` and ``allure-pytest`` reporting enabled, and return
structured results.

No UI code lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from config import settings
from utils.helpers import get_logger

logger = get_logger(__name__)


@dataclass
class TestResult:
    """Outcome of a single pytest test item."""

    node_id: str
    outcome: str  # "passed" | "failed" | "skipped" | "error"
    duration_seconds: float
    message: str | None = None


@dataclass
class PytestRunResult:
    """Aggregate result of one pytest invocation."""

    exit_code: int
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_seconds: float
    results: list[TestResult] = field(default_factory=list)
    html_report_path: Path | None = None
    allure_results_dir: Path | None = None

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.errors == 0


class _ResultCollectorPlugin:
    """A minimal pytest plugin that records per-test outcomes as they happen."""

    def __init__(self) -> None:
        self.results: list[TestResult] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:  # noqa: D102
        if report.when != "call" and report.outcome != "failed":
            # Only record setup/teardown failures in addition to the "call" phase.
            if not (report.when in ("setup", "teardown") and report.outcome == "failed"):
                return
        message = None
        if report.outcome == "failed":
            message = str(report.longrepr)
        self.results.append(
            TestResult(
                node_id=report.nodeid,
                outcome=report.outcome,
                duration_seconds=report.duration,
                message=message,
            )
        )


def run_pytest(
    test_dir: Path | None = None,
    html_report_path: Path | None = None,
    allure_results_dir: Path | None = None,
) -> PytestRunResult:
    """Run pytest against ``test_dir`` and return structured results.

    Args:
        test_dir: Directory (or single file) to run pytest against; defaults to
            ``settings.generated_tests_dir``.
        html_report_path: Where to write the ``pytest-html`` report; defaults to
            ``settings.reports_dir / "pytest_report.html"``.
        allure_results_dir: Where to write raw Allure results; defaults to
            ``settings.reports_dir / "allure-results"``.

    Returns:
        A :class:`PytestRunResult` with per-test outcomes and aggregate counts.
    """
    test_dir = test_dir or settings.generated_tests_dir
    html_report_path = html_report_path or (settings.reports_dir / "pytest_report.html")
    allure_results_dir = allure_results_dir or (settings.reports_dir / "allure-results")

    html_report_path.parent.mkdir(parents=True, exist_ok=True)
    allure_results_dir.mkdir(parents=True, exist_ok=True)

    collector = _ResultCollectorPlugin()
    args = [
        str(test_dir),
        f"--html={html_report_path}",
        "--self-contained-html",
        f"--alluredir={allure_results_dir}",
        "-q",
    ]

    logger.info("Running pytest: %s", " ".join(args))
    exit_code = pytest.main(args, plugins=[collector])

    passed = sum(1 for r in collector.results if r.outcome == "passed")
    failed = sum(1 for r in collector.results if r.outcome == "failed")
    skipped = sum(1 for r in collector.results if r.outcome == "skipped")
    errors = sum(1 for r in collector.results if r.outcome == "error")
    duration = sum(r.duration_seconds for r in collector.results)

    result = PytestRunResult(
        exit_code=int(exit_code),
        total=len(collector.results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        duration_seconds=duration,
        results=collector.results,
        html_report_path=html_report_path,
        allure_results_dir=allure_results_dir,
    )
    logger.info(
        "pytest run complete: %d passed, %d failed, %d skipped, %d errors (exit=%d)",
        passed, failed, skipped, errors, exit_code,
    )
    return result
