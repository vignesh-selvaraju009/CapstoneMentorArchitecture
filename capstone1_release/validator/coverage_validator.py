"""Validate that a set of generated test cases covers the required categories for
an endpoint, and produce a human-readable coverage report.

No UI code lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from llm.llm_generator import TestCase
from parser.openapi_parser import Endpoint
from utils.helpers import get_logger

logger = get_logger(__name__)

REQUIRED_CATEGORIES = (
    "Happy Path",
    "Negative",
    "Boundary",
    "Security",
    "Schema",
    "Authorization",
    "Edge",
)


@dataclass
class CoverageReport:
    """Per-endpoint coverage result."""

    endpoint_path: str
    endpoint_method: str
    covered: dict[str, bool] = field(default_factory=dict)
    test_case_counts: dict[str, int] = field(default_factory=dict)

    @property
    def missing_categories(self) -> list[str]:
        return [category for category, ok in self.covered.items() if not ok]

    @property
    def is_fully_covered(self) -> bool:
        return not self.missing_categories

    def as_text(self) -> str:
        """Render the report as the ✓/✗ checklist shown in the brief."""
        lines = [f"{self.endpoint_method} {self.endpoint_path}"]
        for category in REQUIRED_CATEGORIES:
            mark = "\u2713" if self.covered.get(category) else "\u2717"
            lines.append(f"{mark} {category}")
        return "\n".join(lines)


def _applicable_categories(endpoint: Endpoint) -> tuple[str, ...]:
    """Categories that make sense for this endpoint (e.g. skip Authorization if no auth)."""
    categories = list(REQUIRED_CATEGORIES)
    if not endpoint.auth:
        categories = [c for c in categories if c != "Authorization"]
    return tuple(categories)


def validate_coverage(endpoint: Endpoint, test_cases: list[TestCase]) -> CoverageReport:
    """Check ``test_cases`` (already deduplicated) against the required categories.

    Args:
        endpoint: The endpoint the test cases were generated for.
        test_cases: The (deduplicated) generated test cases for this endpoint.

    Returns:
        A :class:`CoverageReport` with a ✓/✗ flag per applicable category.
    """
    applicable = _applicable_categories(endpoint)
    counts: dict[str, int] = {category: 0 for category in REQUIRED_CATEGORIES}
    for test_case in test_cases:
        if test_case.category in counts:
            counts[test_case.category] += 1

    covered = {category: (counts[category] > 0) for category in applicable}
    # Non-applicable categories (e.g. Authorization on an unauthenticated endpoint)
    # are reported as covered so they don't show up as false failures.
    for category in REQUIRED_CATEGORIES:
        covered.setdefault(category, True)

    report = CoverageReport(
        endpoint_path=endpoint.path,
        endpoint_method=endpoint.method,
        covered=covered,
        test_case_counts=counts,
    )

    if not report.is_fully_covered:
        logger.info(
            "%s %s missing coverage: %s", endpoint.method, endpoint.path, report.missing_categories
        )
    return report
