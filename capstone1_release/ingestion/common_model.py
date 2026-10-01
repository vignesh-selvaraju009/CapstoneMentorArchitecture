from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, cast
from ingestion.document_parser import load_ingestion_config
from parser.openapi_parser import ParsedSpec
@dataclass
class CommonDocument:
    document_id:str; document_type:str
    service_name:Any=None; service_description:Any=None; version:Any=None; base_url:Any=None
    endpoint:Any=None; http_method:Any=None; operation_id:Any=None; summary:Any=None; description:Any=None
    path_parameters:Any=None; query_parameters:Any=None; header_parameters:Any=None; request_body:Any=None
    request_schema:Any=None; response_schema:Any=None; response_status:Any=None; authentication:Any=None
    required_fields:Any=None; optional_fields:Any=None; data_type:Any=None; default_value:Any=None
    allowed_values:Any=None; example_values:Any=None; constraints:Any=None; dependencies:Any=None
    relationships:Any=None; business_rules:Any=None; extra:dict[str,Any]=field(default_factory=lambda: dict[str, Any]())
def _first(data: Any, aliases: list[str]) -> Any:
    if not isinstance(data,dict): return None
    source: dict[str, Any] = cast(dict[str, Any], data)
    lowered: dict[str, Any] = {}
    for key, value in source.items():
        lowered[str(key).lower()] = value
    for a in aliases:
        if a in source:return source[a]
        if a.lower() in lowered:return lowered[a.lower()]
    return None
def normalize_generic(document: Any, document_id: str, document_type: str) -> dict[str, Any]:
    model: dict[str, Any] = load_ingestion_config()["common_document_model"]
    out: dict[str, Any] = {}
    for f in model["fields"]: out[f]=_first(document,model.get("mapping_aliases",{}).get(f,[f]))
    out["document_id"]=document_id; out["document_type"]=document_type
    return out
def normalize_openapi(parsed_spec: ParsedSpec, document_id: str, document_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ep in parsed_spec.endpoints:
        ps=ep.parameters
        out.append({"document_id":document_id,"document_type":document_type,"service_name":parsed_spec.title,"service_description":None,"version":parsed_spec.version,"base_url":parsed_spec.base_url,"endpoint":ep.path,"http_method":ep.method,"operation_id":ep.operation_id,"summary":ep.summary,"description":ep.description,"path_parameters":[asdict(p) for p in ps if p.location=="path"],"query_parameters":[asdict(p) for p in ps if p.location=="query"],"header_parameters":[asdict(p) for p in ps if p.location=="header"],"request_body":asdict(ep.request_body) if ep.request_body else None,"request_schema":ep.request_body.schema if ep.request_body else None,"response_schema":[asdict(r) for r in ep.responses],"response_status":[r.status_code for r in ep.responses],"authentication":[asdict(a) for a in ep.auth],"required_fields":[p.name for p in ps if p.required],"optional_fields":[p.name for p in ps if not p.required],"data_type":[p.schema_type for p in ps],"default_value":[p.default for p in ps if p.default is not None],"allowed_values":[p.enum for p in ps if p.enum],"example_values":None,"constraints":None,"dependencies":None,"relationships":[],"business_rules":[],"extra":{"deprecated":ep.deprecated,"tags":ep.tags}})
    return out
