"""Regression tests for coverage validation and duplicate-checking
(existing TC-generation pipeline features that must keep working).
"""
from __future__ import annotations

from llm.llm_generator import TestCase as LLMTestCase
from parser.openapi_parser import AuthScheme, Endpoint
from validator.coverage_validator import validate_coverage
from validator.duplicate_checker import deduplicate_test_cases


def _endpoint(with_auth: bool = True) -> Endpoint:
    return Endpoint(
        path="/pets/{id}",
        method="get",
        operation_id="getPet",
        summary="Get a pet",
        description=None,
        auth=[AuthScheme(name="BearerAuth", type="http", scheme="bearer")] if with_auth else [],
    )


def _test_case(category: str, title: str = "case", expected_status: int = 200) -> LLMTestCase:
    return LLMTestCase(
        title=title,
        description="desc",
        priority="Medium",
        category=category,
        expected_status=expected_status,
        expected_response=None,
    )


def test_coverage_reports_missing_categories():
    endpoint = _endpoint(with_auth=True)
    cases = [_test_case("Happy Path"), _test_case("Negative")]
    report = validate_coverage(endpoint, cases)

    assert report.covered["Happy Path"] is True
    assert report.covered["Negative"] is True
    assert report.covered["Security"] is False
    assert not report.is_fully_covered
    assert "Security" in report.missing_categories


def test_coverage_skips_authorization_when_no_auth():
    endpoint = _endpoint(with_auth=False)
    report = validate_coverage(endpoint, [])
    assert report.covered["Authorization"] is True


def test_deduplicate_removes_identical_signatures():
    cases = [
        _test_case("Happy Path", title="Same title", expected_status=200),
        _test_case("Happy Path", title="Same title", expected_status=200),
        _test_case("Negative", title="Different case", expected_status=400),
    ]
    deduped = deduplicate_test_cases(cases)
    assert len(deduped) == 2
