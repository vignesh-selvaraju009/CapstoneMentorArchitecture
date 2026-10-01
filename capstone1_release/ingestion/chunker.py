from __future__ import annotations
import hashlib, json
from typing import Any, cast

def _id(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:16]


def chunk_document(document: Any, document_id: str, max_chars: int, overlap_chars: int = 0) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    def emit(text: str, path: str, parent: str | None, kind: str) -> str | None:
        if not text.strip(): return None
        cid = _id(f"{document_id}:{path}:{len(chunks)}")
        chunks.append({"chunk_id":cid,"document_id":document_id,"parent_chunk_id":parent,"path":path,"kind":kind,"text":text})
        return cid

    def walk(value: Any, path: str, parent: str | None = None) -> str | None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            rendered = json.dumps(mapping, ensure_ascii=False, indent=2)
            if len(rendered)<=max_chars:
                return emit(rendered,path,parent,"object") or parent
            # Too large for one chunk: emit a lightweight structural anchor for
            # this object so descendant chunks can still be traced back to it,
            # then recurse into each child using the anchor as their parent.
            anchor_cid = emit(json.dumps({"keys": list(mapping.keys())}, ensure_ascii=False), path, parent, "object_anchor") or parent
            for key, child in mapping.items(): walk(child, f"{path}.{key}", anchor_cid)
            return anchor_cid
        if isinstance(value, list):
            items = cast(list[Any], value)
            for index, child in enumerate(items): walk(child, f"{path}[{index}]", parent)
            return parent
        text = str(value)
        if len(text)<=max_chars: emit(text,path,parent,"value")
        else:
            step=max(1,max_chars-overlap_chars)
            for start in range(0,len(text),step): emit(text[start:start+max_chars],path,parent,"text")
        return parent
    walk(document,"$")
    return chunks
