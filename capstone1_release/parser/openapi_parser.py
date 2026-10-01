"""Parse and validate an OpenAPI 3.x specification into typed dataclasses.

Accepts a local JSON/YAML file path or a URL, resolves all ``$ref`` pointers using
``prance.ResolvingParser`` (which validates the spec as part of resolution), and
extracts everything a test-generation pipeline needs: endpoints, HTTP methods,
path/query/header/cookie parameters, request body schemas, response schemas per
status code, authentication schemes, tags, summaries, and status codes.

No UI code lives here. Designed to be easy to unit test: the public entry point
``parse_spec`` takes a plain string (path or URL) and returns a plain
``ParsedSpec`` dataclass with no external side effects beyond reading the source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prance import ResolvingParser
from prance.util.url import ResolutionError

from utils.helpers import get_logger

logger = get_logger(__name__)

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class OpenAPIParseError(Exception):
    """Raised when a spec cannot be loaded, resolved, or validated."""


@dataclass
class Parameter:
    """A single path/query/header/cookie parameter for an operation."""

    name: str
    location: str  # "path" | "query" | "header" | "cookie"
    required: bool
    schema_type: str | None = None
    description: str | None = None
    default: Any = None
    enum: list[Any] | None = None


@dataclass
class RequestBody:
    """The request body accepted by an operation, if any."""

    required: bool
    content_type: str | None
    schema: dict[str, Any] | None


@dataclass
class ResponseDef:
    """A single documented response for an operation, keyed by status code."""

    status_code: str
    description: str | None
    content_type: str | None
    schema: dict[str, Any] | None


@dataclass
class AuthScheme:
    """A resolved security scheme applicable to an operation."""

    name: str
    type: str  # "http" | "apiKey" | "oauth2" | "openIdConnect"
    scheme: str | None = None  # e.g. "bearer", "basic" (for type == "http")
    bearer_format: str | None = None
    location: str | None = None  # "header" | "query" | "cookie" (for type == "apiKey")
    param_name: str | None = None  # header/query/cookie name (for type == "apiKey")


@dataclass
class Endpoint:
    """A single operation (path + method) extracted from the spec."""

    path: str
    method: str
    operation_id: str | None
    summary: str | None
    description: str | None
    tags: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    responses: list[ResponseDef] = field(default_factory=list)
    auth: list[AuthScheme] = field(default_factory=list)
    deprecated: bool = False


@dataclass
class ParsedSpec:
    """The full parsed specification."""

    title: str
    version: str
    openapi_version: str | None
    base_url: str | None
    endpoints: list[Endpoint] = field(default_factory=list)


def _load_resolved_spec(source: str) -> dict[str, Any]:
    """Parse and fully resolve ``source`` (file path or URL) with prance.

    Prance validates the spec (structurally and against the OpenAPI/Swagger meta
    schema) as part of resolving all ``$ref`` pointers, so a successfully returned
    dict is guaranteed to be a valid, fully-dereferenced specification.
    """
    try:
        parser = ResolvingParser(source, backend="openapi-spec-validator")
    except ResolutionError as exc:
        logger.error("Failed to resolve spec references for %s: %s", source, exc)
        raise OpenAPIParseError(f"Could not resolve references in spec '{source}': {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - prance raises varied exception types
        logger.error("Failed to parse/validate spec %s: %s", source, exc)
        raise OpenAPIParseError(f"Invalid or unreadable OpenAPI spec '{source}': {exc}") from exc

    if not parser.specification:
        raise OpenAPIParseError(f"Spec '{source}' resolved to an empty document")

    return parser.specification


def _extract_security_schemes(spec: dict[str, Any]) -> dict[str, AuthScheme]:
    """Build a lookup of scheme name -> AuthScheme from components.securitySchemes."""
    schemes: dict[str, AuthScheme] = {}
    raw_schemes = (
        spec.get("components", {}).get("securitySchemes", {})
        or spec.get("securityDefinitions", {})  # Swagger 2.0 fallback
        or {}
    )
    for name, raw in raw_schemes.items():
        scheme_type = raw.get("type", "unknown")
        schemes[name] = AuthScheme(
            name=name,
            type=scheme_type,
            scheme=raw.get("scheme"),
            bearer_format=raw.get("bearerFormat"),
            location=raw.get("in"),
            param_name=raw.get("name"),
        )
    return schemes


def _resolve_auth_for_operation(
    operation: dict[str, Any],
    global_security: list[dict[str, list[str]]],
    schemes: dict[str, AuthScheme],
) -> list[AuthScheme]:
    """Resolve the effective security requirements for one operation.

    An operation-level ``security`` overrides the global one entirely (per the
    OpenAPI spec, including an empty list meaning "no auth required").
    """
    security_requirements = operation.get("security", global_security)
    resolved: list[AuthScheme] = []
    for requirement in security_requirements or []:
        for scheme_name in requirement:
            scheme = schemes.get(scheme_name)
            if scheme is not None:
                resolved.append(scheme)
            else:
                logger.warning("Security scheme '%s' referenced but not defined", scheme_name)
    return resolved


def _extract_parameters(
    path_item: dict[str, Any], operation: dict[str, Any]
) -> list[Parameter]:
    """Combine path-level and operation-level parameters (operation takes precedence)."""
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_param in path_item.get("parameters", []) + operation.get("parameters", []):
        key = (raw_param.get("name", ""), raw_param.get("in", ""))
        combined[key] = raw_param

    parameters: list[Parameter] = []
    for raw_param in combined.values():
        schema = raw_param.get("schema", {}) or {}
        parameters.append(
            Parameter(
                name=raw_param.get("name", ""),
                location=raw_param.get("in", ""),
                required=bool(raw_param.get("required", False)),
                schema_type=schema.get("type"),
                description=raw_param.get("description"),
                default=schema.get("default"),
                enum=schema.get("enum"),
            )
        )
    return parameters


def _extract_request_body(operation: dict[str, Any]) -> RequestBody | None:
    """Extract the request body schema for the first supported content type present."""
    request_body = operation.get("requestBody")
    if not request_body:
        return None

    content = request_body.get("content", {}) or {}
    for content_type in ("application/json", *content.keys()):
        media = content.get(content_type)
        if media is not None:
            return RequestBody(
                required=bool(request_body.get("required", False)),
                content_type=content_type,
                schema=media.get("schema"),
            )
    return RequestBody(required=bool(request_body.get("required", False)), content_type=None, schema=None)


def _extract_responses(operation: dict[str, Any]) -> list[ResponseDef]:
    """Extract one ResponseDef per documented status code."""
    responses: list[ResponseDef] = []
    for status_code, raw_response in (operation.get("responses", {}) or {}).items():
        content = (raw_response or {}).get("content", {}) or {}
        content_type = next(iter(content), None)
        schema = content[content_type].get("schema") if content_type else None
        responses.append(
            ResponseDef(
                status_code=str(status_code),
                description=(raw_response or {}).get("description"),
                content_type=content_type,
                schema=schema,
            )
        )
    return responses


def _extract_base_url(spec: dict[str, Any]) -> str | None:
    servers = spec.get("servers") or []
    if servers:
        return servers[0].get("url")
    # Swagger 2.0 fallback
    host = spec.get("host")
    if host:
        base_path = spec.get("basePath", "")
        schemes = spec.get("schemes") or ["https"]
        return f"{schemes[0]}://{host}{base_path}"
    return None


def parse_spec(source: str) -> ParsedSpec:
    """Parse an OpenAPI 3.x spec from a local file path, or URL into a ``ParsedSpec``.

    Args:
        source: Path to a local ``.json``/``.yaml``/``.yml`` file, or a URL pointing
            to one.

    Returns:
        A fully populated :class:`ParsedSpec`.

    Raises:
        OpenAPIParseError: if the spec cannot be read, resolved, or validated.
    """
    logger.info("Parsing OpenAPI spec from: %s", source)
    spec = _load_resolved_spec(source)

    info = spec.get("info", {}) or {}
    schemes = _extract_security_schemes(spec)
    global_security = spec.get("security", []) or []

    endpoints: list[Endpoint] = []
    for path, path_item in (spec.get("paths", {}) or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if operation is None:
                continue
            endpoints.append(
                Endpoint(
                    path=path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary"),
                    description=operation.get("description"),
                    tags=list(operation.get("tags", [])),
                    parameters=_extract_parameters(path_item, operation),
                    request_body=_extract_request_body(operation),
                    responses=_extract_responses(operation),
                    auth=_resolve_auth_for_operation(operation, global_security, schemes),
                    deprecated=bool(operation.get("deprecated", False)),
                )
            )

    logger.info("Parsed %d endpoint(s) from %s", len(endpoints), source)

    return ParsedSpec(
        title=info.get("title", "Untitled API"),
        version=info.get("version", "0.0.0"),
        openapi_version=spec.get("openapi") or spec.get("swagger"),
        base_url=_extract_base_url(spec),
        endpoints=endpoints,
    )
