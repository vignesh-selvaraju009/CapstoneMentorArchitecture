"""Aggregate pytest + Newman execution results and coverage validation output
into unified HTML, JSON, and Allure-consumable reports.

No UI code lives here.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template

from config import settings
from runner.newman_runner import NewmanRunResult
from runner.pytest_runner import PytestRunResult
from utils.helpers import get_logger, write_json
from validator.coverage_validator import CoverageReport

logger = get_logger(__name__)

_STATUS_MISMATCH_RE = re.compile(r"Expected status (\d+), got (\d+)")

_HTML_TEMPLATE = Template(
    """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>API Test Suite Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 2rem; color: #222; }
    h1, h2 { color: #1a1a2e; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }
    th { background: #f0f0f5; }
    .pass { color: #0a7d2c; font-weight: bold; }
    .fail { color: #c0392b; font-weight: bold; }
    .summary-box { display: inline-block; padding: 0.75rem 1.25rem; margin-right: 1rem;
                   border-radius: 6px; background: #f7f7fb; }
  </style>
</head>
<body>
  <h1>API Test Suite Report</h1>
  <p>Generated at {{ generated_at }}</p>

  <h2>Pytest Summary</h2>
  <div class="summary-box">Total: {{ pytest_summary.total }}</div>
  <div class="summary-box">Passed: {{ pytest_summary.passed }}</div>
  <div class="summary-box">Failed: {{ pytest_summary.failed }}</div>
  <div class="summary-box">Skipped: {{ pytest_summary.skipped }}</div>
  <div class="summary-box">Duration: {{ "%.2f"|format(pytest_summary.duration_seconds) }}s</div>

  <h2>Newman Summary</h2>
  {% if newman_summary.available %}
  <div class="summary-box">Requests: {{ newman_summary.total_requests }}</div>
  <div class="summary-box">Assertions: {{ newman_summary.total_assertions }}</div>
  <div class="summary-box">Failed assertions: {{ newman_summary.failed_assertions }}</div>
  {% else %}
  <p><em>{{ newman_summary.error }}</em></p>
  {% endif %}

  <h2>Status Code Comparisons (expected vs actual)</h2>
  <table>
    <tr><th>Test</th><th>Expected</th><th>Actual</th><th>Match</th></tr>
    {% for c in comparisons %}
    <tr>
      <td>{{ c.test_name }}</td>
      <td>{{ c.expected_status if c.expected_status != -1 else "n/a" }}</td>
      <td>{{ c.actual_status if c.actual_status is not none else "n/a" }}</td>
      <td class="{{ 'pass' if c.status_match else 'fail' }}">{{ "MATCH" if c.status_match else "MISMATCH" }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Coverage</h2>
  <table>
    <tr><th>Endpoint</th>{% for cat in categories %}<th>{{ cat }}</th>{% endfor %}</tr>
    {% for report in coverage_reports %}
    <tr>
      <td>{{ report.endpoint_method }} {{ report.endpoint_path }}</td>
      {% for cat in categories %}
      <td class="{{ 'pass' if report.covered.get(cat, false) else 'fail' }}">
        {{ "\u2713" if report.covered.get(cat, false) else "\u2717" }}
      </td>
      {% endfor %}
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""
)


@dataclass
class ComparisonResult:
    """Expected vs actual status for a single test, derived from run results."""

    test_name: str
    expected_status: int
    actual_status: int | None
    status_match: bool
    response_time_ms: float | None = None


@dataclass
class AggregatedReport:
    """The full aggregated report for one execution run."""

    generated_at: str
    pytest_summary: dict[str, Any]
    newman_summary: dict[str, Any]
    coverage_reports: list[dict[str, Any]]
    comparisons: list[dict[str, Any]] = field(default_factory=list)


def _extract_status_mismatch(message: str | None) -> tuple[int, int] | None:
    if not message:
        return None
    match = _STATUS_MISMATCH_RE.search(message)
    if not match:
        return None
    expected, actual = match.groups()
    return int(expected), int(actual)


def build_comparisons(
    pytest_result: PytestRunResult,
    newman_result: NewmanRunResult,
    expected_status_by_function: dict[str, int] | None = None,
) -> list[ComparisonResult]:
    """Derive expected-vs-actual status comparisons from pytest and Newman results.

    For pytest: failed tests carry an "Expected status X, got Y" message (from the
    assertion in ``templates/pytest_template.j2``) when the request completed but
    got the wrong status; passed tests are assumed to match (expected == actual)
    since the assertion succeeded. Any other failure (connection error, timeout,
    unresolved host, etc.) still gets a row, with ``actual_status=None``, using
    ``expected_status_by_function`` (keyed by the pytest function name, i.e. the
    part of the node id after "::") to fill in the expected status when known, so
    the comparison table is never silently empty.
    For Newman: each request's ``pm.test(... status ...)`` assertion result maps
    directly to a pass/fail; the actual status code is read from the response.
    """
    expected_status_by_function = expected_status_by_function or {}
    comparisons: list[ComparisonResult] = []

    for test_result in pytest_result.results:
        mismatch = _extract_status_mismatch(test_result.message)
        function_name = test_result.node_id.rsplit("::", 1)[-1]
        known_expected = expected_status_by_function.get(function_name)

        if mismatch:
            expected, actual = mismatch
            comparisons.append(
                ComparisonResult(test_name=test_result.node_id, expected_status=expected, actual_status=actual, status_match=False)
            )
        elif test_result.outcome == "passed":
            expected = known_expected if known_expected is not None else -1
            comparisons.append(
                ComparisonResult(test_name=test_result.node_id, expected_status=expected, actual_status=expected, status_match=True)
            )
        else:
            comparisons.append(
                ComparisonResult(
                    test_name=test_result.node_id,
                    expected_status=known_expected if known_expected is not None else -1,
                    actual_status=None,
                    status_match=False,
                )
            )

    if newman_result.available:
        for request_result in newman_result.requests:
            status_assertion = next(
                (a for a in request_result.assertions if "status code" in a.name.lower()), None
            )
            if status_assertion is None:
                continue
            comparisons.append(
                ComparisonResult(
                    test_name=request_result.name,
                    expected_status=-1,
                    actual_status=request_result.status_code,
                    status_match=status_assertion.passed,
                    response_time_ms=request_result.response_time_ms,
                )
            )

    return comparisons


def build_report(
    pytest_result: PytestRunResult,
    newman_result: NewmanRunResult,
    coverage_reports: list[CoverageReport],
    expected_status_by_function: dict[str, int] | None = None,
) -> AggregatedReport:
    """Combine pytest/newman results and coverage reports into one aggregated report."""
    comparisons = build_comparisons(pytest_result, newman_result, expected_status_by_function)

    pytest_summary = {
        "total": pytest_result.total,
        "passed": pytest_result.passed,
        "failed": pytest_result.failed,
        "skipped": pytest_result.skipped,
        "errors": pytest_result.errors,
        "duration_seconds": pytest_result.duration_seconds,
        "exit_code": pytest_result.exit_code,
    }
    newman_summary = {
        "available": newman_result.available,
        "total_requests": newman_result.total_requests,
        "total_assertions": newman_result.total_assertions,
        "failed_assertions": newman_result.failed_assertions,
        "error": newman_result.error,
    }

    return AggregatedReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        pytest_summary=pytest_summary,
        newman_summary=newman_summary,
        coverage_reports=[asdict(report) for report in coverage_reports],
        comparisons=[asdict(c) for c in comparisons],
    )


def write_json_report(report: AggregatedReport, output_path: Path | None = None) -> Path:
    """Write the aggregated report as JSON."""
    output_path = output_path or (settings.reports_dir / "report.json")
    write_json(output_path, asdict(report))
    logger.info("Wrote JSON report: %s", output_path)
    return output_path


def write_html_report(report: AggregatedReport, output_path: Path | None = None) -> Path:
    """Render and write the aggregated report as a standalone HTML file."""
    output_path = output_path or (settings.reports_dir / "report.html")
    categories = ("Happy Path", "Negative", "Boundary", "Security", "Schema", "Authorization", "Edge")
    html = _HTML_TEMPLATE.render(
        generated_at=report.generated_at,
        pytest_summary=report.pytest_summary,
        newman_summary=report.newman_summary,
        comparisons=report.comparisons,
        coverage_reports=report.coverage_reports,
        categories=categories,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote HTML report: %s", output_path)
    return output_path


def generate_allure_report(
    allure_results_dir: Path | None = None,
    allure_report_dir: Path | None = None,
    executable: str = "allure",
) -> Path | None:
    """Render a static Allure HTML report from raw results via the ``allure`` CLI.

    Returns the report directory path, or ``None`` if the ``allure`` CLI is not
    installed (this is optional tooling; raw results are still available under
    ``allure_results_dir`` for later processing).
    """
    allure_results_dir = allure_results_dir or (settings.reports_dir / "allure-results")
    allure_report_dir = allure_report_dir or (settings.reports_dir / "allure-report")

    if shutil.which(executable) is None:
        logger.warning(
            "Allure CLI ('%s') not found on PATH; skipping static report generation. "
            "Raw results remain available at %s", executable, allure_results_dir,
        )
        return None

    command = [executable, "generate", str(allure_results_dir), "-o", str(allure_report_dir), "--clean"]
    logger.info("Running: %s", " ".join(command))
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=300, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("Failed to generate Allure report: %s", exc)
        return None

    logger.info("Generated Allure report: %s", allure_report_dir)
    return allure_report_dir


def generate_reports(
    pytest_result: PytestRunResult,
    newman_result: NewmanRunResult,
    coverage_reports: list[CoverageReport],
    expected_status_by_function: dict[str, int] | None = None,
) -> dict[str, Path | None]:
    """Convenience entry point: build and write JSON + HTML + Allure reports.

    Returns:
        A dict with keys "json", "html", "allure" mapping to their output paths
        (``allure`` may be ``None`` if the Allure CLI is unavailable).
    """
    report = build_report(pytest_result, newman_result, coverage_reports, expected_status_by_function)
    json_path = write_json_report(report)
    html_path = write_html_report(report)
    allure_path = generate_allure_report()
    return {"json": json_path, "html": html_path, "allure": allure_path}
