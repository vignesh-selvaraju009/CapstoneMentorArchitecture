"""Convert a parsed :class:`~parser.openapi_parser.Endpoint` into a compact,
human-readable text block suitable for use as LLM prompt context.

Rather than sending an entire (potentially huge) OpenAPI document to the LLM,
callers should parse the spec once with ``parser.openapi_parser.parse_spec`` and
then call :func:`summarize_endpoint` per endpoint to build the small, focused
context that goes into the prompt (see ``llm/prompt_builder.py``).

No UI code lives here.
"""
from __future__ import annotations

from typing import Any

from parser.openapi_parser import Endpoint, Parameter, ResponseDef
from utils.helpers import get_logger

logger = get_logger(__name__)


def _describe_auth(endpoint: Endpoint) -> str:
    if not endpoint.auth:
        return "None"
    parts = []
    for scheme in endpoint.auth:
        if scheme.type == "http":
            parts.append(scheme.scheme.capitalize() if scheme.scheme else "HTTP")
        elif scheme.type == "apiKey":
            parts.append(f"API Key ({scheme.location}: {scheme.param_name})")
        else:
            parts.append(scheme.type)
    return ", ".join(parts)


def _describe_parameter(param: Parameter) -> str:
    required = "required" if param.required else "optional"
    type_label = param.schema_type or "string"
    extras = []
    if param.enum:
        extras.append(f"enum={param.enum}")
    if param.default is not None:
        extras.append(f"default={param.default}")
    extra_str = f" ({', '.join(extras)})" if extras else ""
    return f"- {param.name} [{param.location}] {type_label}, {required}{extra_str}"


def _schema_field_names(schema: dict[str, Any] | None) -> list[str]:
    """Best-effort extraction of top-level field names from a JSON schema object."""
    if not schema:
        return []
    if schema.get("type") == "array":
        return _schema_field_names(schema.get("items"))
    properties = schema.get("properties")
    if properties:
        return list(properties.keys())
    return []


def _describe_response(response: ResponseDef) -> str:
    fields = _schema_field_names(response.schema)
    if fields:
        body = "{ " + ", ".join(fields) + " }"
    else:
        body = "(no schema)" if not response.description else response.description
    return f"{response.status_code}\n{body}"


def summarize_endpoint(endpoint: Endpoint) -> str:
    """Build the compact prompt-context text block for a single endpoint.

    Example output::

        GET /users/{id}

        Authentication:
        Bearer

        Request Parameters

        - id [path] integer, required

        Response

        200
        { id, name, email }
    """
    lines: list[str] = [f"{endpoint.method} {endpoint.path}"]

    if endpoint.summary:
        lines.append(endpoint.summary)

    lines.append("")
    lines.append("Authentication:")
    lines.append(_describe_auth(endpoint))

    if endpoint.parameters:
        lines.append("")
        lines.append("Request Parameters")
        lines.append("")
        lines.extend(_describe_parameter(p) for p in endpoint.parameters)

    if endpoint.request_body is not None:
        lines.append("")
        lines.append("Request Body")
        lines.append("")
        body_fields = _schema_field_names(endpoint.request_body.schema)
        required = "required" if endpoint.request_body.required else "optional"
        if body_fields:
            lines.append(f"({required}) {{ {', '.join(body_fields)} }}")
        else:
            lines.append(f"({required}) {endpoint.request_body.content_type or 'unspecified'}")

    if endpoint.responses:
        lines.append("")
        lines.append("Response")
        lines.append("")
        for response in sorted(endpoint.responses, key=lambda r: r.status_code):
            lines.append(_describe_response(response))
            lines.append("")

    summary_text = "\n".join(lines).rstrip() + "\n"
    logger.debug("Built schema summary for %s %s (%d chars)", endpoint.method, endpoint.path, len(summary_text))
    return summary_text
