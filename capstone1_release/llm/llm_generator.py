"""Call the OpenAI GPT API to generate structured API test cases from a prompt
built by ``llm/prompt_builder.py``.

Parses/validates the JSON response into typed :class:`TestCase` objects, retrying
once with a "please return valid JSON only" repair prompt if the first response
fails to parse.

If the API call fails because of a quota/rate-limit error (HTTP 429), falls back
to offline, pattern-based test-case generation sourced directly from the local
knowledge base (``knowledge_base/test_patterns.json`` and
``knowledge_base/security_rules.json``) so the rest of the pipeline can still be
exercised without a working OpenAI key.

No UI code lives here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import APIError, OpenAI

from config import settings
from llm.prompt_builder import parse_llm_json_response
from utils.helpers import get_logger

logger = get_logger(__name__)

VALID_CATEGORIES = {
    "Happy Path",
    "Negative",
    "Boundary",
    "Security",
    "Schema",
    "Authorization",
    "Edge",
}
VALID_PRIORITIES = {"High", "Medium", "Low"}


class LLMGenerationError(Exception):
    """Raised when the LLM cannot produce a usable, parseable set of test cases."""


_QUOTA_ERROR_CODES = {"insufficient_quota", "rate_limit_exceeded", "invalid_api_key"}
_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")


def _is_quota_or_rate_limit_error(exc: APIError) -> bool:
    """Return True if ``exc`` represents an HTTP 429 (quota/rate-limit) or 401
    (missing/invalid API key) error — cases where offline fallback should kick in.
    """
    code = getattr(exc, "code", None)
    status_code = getattr(exc, "status_code", None)
    return code in _QUOTA_ERROR_CODES or status_code in (429, 401)


@dataclass
class TestCase:
    """A single generated API test case."""

    title: str
    description: str
    priority: str
    category: str
    expected_status: int
    expected_response: Any
    assertions: list[str] = field(default_factory=list)


def _to_test_case(raw: dict[str, Any]) -> TestCase:
    priority = raw.get("priority", "Medium")
    if priority not in VALID_PRIORITIES:
        priority = "Medium"

    category = raw.get("category", "Edge")
    if category not in VALID_CATEGORIES:
        category = "Edge"

    try:
        expected_status = int(raw.get("expected_status", 0))
    except (TypeError, ValueError):
        expected_status = 0

    return TestCase(
        title=str(raw.get("title", "")).strip() or "Untitled test case",
        description=str(raw.get("description", "")).strip(),
        priority=priority,
        category=category,
        expected_status=expected_status,
        expected_response=raw.get("expected_response"),
        assertions=[str(a) for a in raw.get("assertions", [])],
    )


def _load_json_entries(path, list_key: str) -> list[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load fallback knowledge base file %s: %s", path, exc)
        return []
    return data.get(list_key, [])


def _pattern_to_test_case(entry: dict[str, Any]) -> TestCase:
    """Convert a raw ``test_patterns.json``/``security_rules.json`` entry into a
    :class:`TestCase`, used when falling back to offline generation.
    """
    description = str(entry.get("description", ""))
    status_match = _STATUS_RE.search(description)
    expected_status = int(status_match.group(1)) if status_match else 200

    category = entry.get("category", "Edge")
    if category not in VALID_CATEGORIES:
        category = "Edge"
    
    priority = "High" if category in {"Security", "Negative"} else "Medium"

    return TestCase(
        title=f"[Offline Fallback] {entry.get('title', 'Untitled pattern')}",
        description=(
            f"{description} (Auto-generated offline because the OpenAI API was unavailable; "
            "not reviewed by the LLM.)"
        ),
        priority=priority,
        category=category,
        expected_status=expected_status,
        expected_response=f"Response matches documented behavior for status {expected_status}.",
        assertions=[
            f"Response status code is {expected_status}",
            "Response body matches the documented/expected schema for this scenario",
        ],
    )


class LLMGenerator:
    """Thin wrapper around the OpenAI chat completions API for test-case generation."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self._model = model or settings.openai_model
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self.last_used_fallback = False

    def generate_fallback_test_cases(self, endpoint_method: str | None = None) -> list[TestCase]:
        """Build a generic test suite directly from the local knowledge base,
        without calling the LLM.

        Used automatically by :meth:`generate_test_cases` when the OpenAI API
        returns a quota/rate-limit (429) error, so the rest of the pipeline
        (dedup, coverage, generators, runners, reports) can still be exercised.
        """
        method = (endpoint_method or "").upper()

        patterns = _load_json_entries(settings.test_patterns_file, "patterns")
        applicable_patterns = [
            p for p in patterns if not p.get("methods") or method in p.get("methods", [])
        ]

        security_rules = _load_json_entries(settings.security_rules_file, "rules")

        entries = applicable_patterns + security_rules
        test_cases = [_pattern_to_test_case(entry) for entry in entries]
        logger.info(
            "Generated %d offline fallback test case(s) for method %s", len(test_cases), method or "ANY"
        )
        return test_cases

    def _call_openai(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": "You return JSON only, with no extra commentary."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise LLMGenerationError("LLM returned an empty response")
        return content

    def generate_test_cases(
        self,
        prompt: str,
        max_retries: int = 1,
        endpoint_method: str | None = None,
        allow_fallback: bool = True,
    ) -> list[TestCase]:
        """Send ``prompt`` to the LLM and return parsed, validated test cases.

        Args:
            prompt: The full prompt produced by ``llm.prompt_builder.build_prompt``.
            max_retries: How many times to retry with a JSON-repair instruction if
                parsing fails.
            endpoint_method: The HTTP method of the endpoint being tested (e.g.
                "GET"), used to filter patterns if falling back to offline
                generation.
            allow_fallback: If True (default), a 429 quota/rate-limit error from
                OpenAI triggers offline, pattern-based fallback generation instead
                of raising. Set to False to always raise on API errors.

        Raises:
            LLMGenerationError: if the API call fails (and fallback is disabled
                or not applicable), or the response still cannot be parsed after
                all retries are exhausted.
        """
        current_prompt = prompt
        last_error: Exception | None = None
        self.last_used_fallback = False

        for attempt in range(max_retries + 1):
            try:
                raw_response = self._call_openai(current_prompt)
            except APIError as exc:
                logger.error("OpenAI API error on attempt %d: %s", attempt + 1, exc)
                if allow_fallback and _is_quota_or_rate_limit_error(exc):
                    logger.warning(
                        "OpenAI quota/rate-limit error - falling back to offline pattern-based test cases: %s",
                        exc,
                    )
                    self.last_used_fallback = True
                    return self.generate_fallback_test_cases(endpoint_method)
                raise LLMGenerationError(f"OpenAI API call failed: {exc}") from exc

            try:
                raw_cases = parse_llm_json_response(raw_response)
                test_cases = [_to_test_case(item) for item in raw_cases]
                logger.info("Generated %d test case(s) on attempt %d", len(test_cases), attempt + 1)
                return test_cases
            except ValueError as exc:
                last_error = exc
                logger.warning("Failed to parse LLM response on attempt %d: %s", attempt + 1, exc)
                current_prompt = (
                    f"{prompt}\n\nYour previous response was not valid JSON ({exc}). "
                    "Return ONLY a valid JSON array, with no markdown formatting or commentary."
                )

        raise LLMGenerationError(f"LLM did not return parseable JSON after {max_retries + 1} attempt(s): {last_error}")
