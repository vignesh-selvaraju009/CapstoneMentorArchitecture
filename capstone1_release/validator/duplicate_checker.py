"""Remove duplicate/near-duplicate generated test cases for a single endpoint.

Two test cases are considered duplicates if they share the same normalized
signature: (category, expected_status, normalized title). This is a cheap,
deterministic check that runs before the (optional) coverage validation step.

No UI code lives here.
"""
from __future__ import annotations

from llm.llm_generator import TestCase
from utils.helpers import get_logger, safe_filename

logger = get_logger(__name__)


def _signature(test_case: TestCase) -> tuple[str, int, str]:
    return (test_case.category, test_case.expected_status, safe_filename(test_case.title))


def deduplicate_test_cases(test_cases: list[TestCase]) -> list[TestCase]:
    """Return ``test_cases`` with duplicates removed, preserving first-seen order.

    Args:
        test_cases: Test cases generated for a single endpoint.

    Returns:
        A new list with duplicate signatures removed.
    """
    seen: set[tuple[str, int, str]] = set()
    unique: list[TestCase] = []

    for test_case in test_cases:
        signature = _signature(test_case)
        if signature in seen:
            logger.debug("Dropping duplicate test case: %s", test_case.title)
            continue
        seen.add(signature)
        unique.append(test_case)

    removed = len(test_cases) - len(unique)
    if removed:
        logger.info("Removed %d duplicate test case(s), %d remain", removed, len(unique))
    return unique
