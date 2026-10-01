"""Render one pytest test-module file per validated test case, using
``templates/pytest_template.j2``.

Since the LLM/test-case schema (see ``llm/llm_generator.TestCase``) does not
carry concrete request parameter *values*, this generator derives reasonable
request values from the endpoint's parameter definitions and simple heuristics
based on the test case's category/title (e.g. an out-of-range path parameter
for a "Negative"/invalid-ID test, a SQL injection payload for a matching
"Security" test, no Authorization header for a "missing auth" test).

No UI code lives here.
"""
from __future__ import annotations

from pathlib import Path

from config import settings
from llm.llm_generator import TestCase
from parser.openapi_parser import Endpoint, Parameter
from utils.helpers import get_logger, safe_filename
from jinja2 import Environment, FileSystemLoader

logger = get_logger(__name__)

SQL_INJECTION_PAYLOAD = "' OR '1'='1"
NEGATIVE_ID_HINTS = ("invalid", "not found", "not-found", "non-existent", "nonexistent", "missing", "unknown")
MISSING_AUTH_HINTS = ("missing auth", "no auth", "without auth", "unauthenticated", "unauthorized")
EXPIRED_AUTH_HINTS = ("expired", "malformed token", "invalid token", "tampered")
SQLI_HINTS = ("sql injection", "sqli", "sql-injection")


def _get_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(settings.templates_dir)), keep_trailing_newline=True)


def sample_value_for_type(param: Parameter) -> object:
    if param.default is not None:
        return param.default
    if param.enum:
        return param.enum[0]
    if param.schema_type in ("integer", "number"):
        return 1
    if param.schema_type == "boolean":
        return True
    return "sample"


def _resolve_param_value(param: Parameter, test_case: TestCase) -> object:
    text = f"{test_case.title} {test_case.description}".lower()

    if test_case.category == "Security" and any(hint in text for hint in SQLI_HINTS):
        return SQL_INJECTION_PAYLOAD

    if param.location == "path" and test_case.category == "Negative" and any(hint in text for hint in NEGATIVE_ID_HINTS):
        return 999999999 if param.schema_type == "integer" else "invalid-id"

    return sample_value_for_type(param)


def _resolve_headers(endpoint: Endpoint, test_case: TestCase) -> dict[str, str]:
    text = f"{test_case.title} {test_case.description}".lower()
    if not endpoint.auth:
        return {}

    if any(hint in text for hint in MISSING_AUTH_HINTS):
        return {}
    if any(hint in text for hint in EXPIRED_AUTH_HINTS):
        return {"Authorization": "Bearer expired.invalid.token"}
    # "__AUTH_TOKEN__" is substituted at runtime with the real AUTH_TOKEN env
    # value inside the rendered test module (see pytest_template.j2).
    return {"Authorization": "Bearer __AUTH_TOKEN__"}


def _field_assertions_from_expected_response(expected_response: object) -> list[str]:
    if isinstance(expected_response, dict):
        return [str(key) for key in expected_response.keys()]
    return []


def _build_function_context(endpoint: Endpoint, test_case: TestCase) -> dict:
    path_params = {p.name: _resolve_param_value(p, test_case) for p in endpoint.parameters if p.location == "path"}
    query_params = {p.name: _resolve_param_value(p, test_case) for p in endpoint.parameters if p.location == "query"}
    headers = _resolve_headers(endpoint, test_case)
    endpoint_slug = safe_filename(f"{endpoint.method} {endpoint.path}")

    return {
        "function_name": f"test_{endpoint_slug}_{safe_filename(test_case.title)}",
        "title": test_case.title,
        "description": test_case.description,
        "category": test_case.category,
        "method": endpoint.method,
        "path_template": endpoint.path,
        "path_params": path_params,
        "query_params": query_params,
        "headers": headers,
        "expected_status": test_case.expected_status,
        "field_assertions": _field_assertions_from_expected_response(test_case.expected_response),
        "manual_assertions": test_case.assertions,
    }


def generate_pytest_suite(
    endpoint: Endpoint,
    test_cases: list[TestCase],
    base_url: str,
    output_dir: Path | None = None,
) -> list[Path]:
    """Generate one pytest file per test case for an endpoint.

    Args:
        endpoint: The endpoint the test cases belong to.
        test_cases: Validated, deduplicated test cases for this endpoint.
        base_url: The API base URL (from ``ParsedSpec.base_url``) to embed in
            each generated file.
        output_dir: Directory to write files into (defaults to
            ``settings.generated_tests_dir``).

    Returns:
        List of paths to the generated files, in the same order as ``test_cases``.
    """
    output_dir = output_dir or settings.generated_tests_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    env = _get_env()
    template = env.get_template("pytest_template.j2")

    written: list[Path] = []
    for test_case in test_cases:
        func_context = _build_function_context(endpoint, test_case)
        rendered = template.render(
            module_docstring=f"Generated test: {test_case.title} ({endpoint.method} {endpoint.path})",
            base_url=base_url or "",
            functions=[func_context],
        )
        file_name = f"{func_context['function_name']}.py"
        file_path = output_dir / file_name
        file_path.write_text(rendered, encoding="utf-8")
        written.append(file_path)

    logger.info("Generated %d pytest file(s) for %s %s in %s", len(written), endpoint.method, endpoint.path, output_dir)
    return written
