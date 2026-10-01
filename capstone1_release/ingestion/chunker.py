from __future__ import annotations
import hashlib, json
def _id(v): return hashlib.sha1(v.encode()).hexdigest()[:16]
def chunk_document(document, document_id, max_chars, overlap_chars=0):
    chunks=[]
    def emit(text,path,parent,kind):
        if not text.strip(): return None
        cid=_id(f"{document_id}:{path}:{len(chunks)}")
        chunks.append({"chunk_id":cid,"document_id":document_id,"parent_chunk_id":parent,"path":path,"kind":kind,"text":text})
        return cid
    def walk(v,path,parent=None):
        if isinstance(v,dict):
            rendered=json.dumps(v,ensure_ascii=False,indent=2)
            if len(rendered)<=max_chars:
                return emit(rendered,path,parent,"object") or parent
            # Too large for one chunk: emit a lightweight structural anchor for
            # this object so descendant chunks can still be traced back to it,
            # then recurse into each child using the anchor as their parent.
            anchor_cid = emit(json.dumps({"keys": list(v.keys())}, ensure_ascii=False), path, parent, "object_anchor") or parent
            for k,x in v.items(): walk(x,f"{path}.{k}",anchor_cid)
            return anchor_cid
        if isinstance(v,list):
            for i,x in enumerate(v): walk(x,f"{path}[{i}]",parent)
            return parent
        text=str(v)
        if len(text)<=max_chars: emit(text,path,parent,"value")
        else:
            step=max(1,max_chars-overlap_chars)
            for start in range(0,len(text),step): emit(text[start:start+max_chars],path,parent,"text")
        return parent
    walk(document,"$")
    return chunks
