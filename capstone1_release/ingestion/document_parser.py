from __future__ import annotations
import json, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
import yaml
from utils.helpers import read_json
def load_ingestion_config():
    return read_json(Path(__file__).resolve().parent.parent/"config"/"ingestion_config.json", default={})
def _xml_to_dict(element):
    children=list(element)
    if not children: return (element.text or "").strip()
    result={"@attributes":dict(element.attrib)} if element.attrib else {}
    for child in children:
        value=_xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag],list): result[child.tag]=[result[child.tag]]
            result[child.tag].append(value)
        else: result[child.tag]=value
    return {element.tag:result}
def parse_file(path):
    p=Path(path); ext=p.suffix.lower(); parser=load_ingestion_config().get("parsers",{}).get(ext)
    if parser=="structured":
        text=p.read_text(encoding="utf-8")
        return json.loads(text) if ext==".json" else yaml.safe_load(text)
    if parser=="xml": return _xml_to_dict(ET.parse(p).getroot())
    if parser=="text": return p.read_text(encoding="utf-8",errors="replace")
    raise ValueError(f"Unsupported document extension: {ext}")
def classify_document(document, extension):
    rules=load_ingestion_config().get("classification",{})
    text=json.dumps(document,ensure_ascii=False).lower() if not isinstance(document,str) else document.lower()
    for rule in rules.get("rules",[]):
        if any(str(s).lower() in text for s in rule.get("signals",[])): return rule.get("name","unknown")
    return rules.get("default","unknown")
