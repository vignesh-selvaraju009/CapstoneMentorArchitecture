from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any
import faiss, numpy as np
from config import settings
from ingestion.document_parser import load_ingestion_config

SentenceTransformer: Any = None


@lru_cache(maxsize=4)
def _load_sentence_transformer(model_name: str, model_class: Any = None) -> Any:
    if model_class is None:
        from sentence_transformers import SentenceTransformer as model_class
    return model_class(model_name)


class DocumentVectorStore:
    def __init__(self,index_path=None):
        cfg=load_ingestion_config().get("embedding",{})
        self.model_name=cfg.get("model") or settings.embedding_model
        self.index_path=Path(index_path or settings.faiss_index_path.parent/"document_chunks.faiss")
        self.model=None; self.index=None; self.chunks=[]
    def _embed(self,texts):
        if self.model is None:
            self.model=_load_sentence_transformer(self.model_name, SentenceTransformer)
        v=self.model.encode(texts,convert_to_numpy=True,show_progress_bar=False).astype("float32")
        faiss.normalize_L2(v); return v
    def build(self,chunks):
        if not chunks: raise ValueError("No chunks to embed")
        self.chunks=chunks; v=self._embed([c["text"] for c in chunks])
        self.index=faiss.IndexFlatIP(v.shape[1]); self.index.add(v)
    def save(self):
        self.index_path.parent.mkdir(parents=True,exist_ok=True); faiss.write_index(self.index,str(self.index_path))
        self.index_path.with_suffix(".meta.json").write_text(json.dumps(self.chunks,indent=2),encoding="utf-8")
    def load(self):
        meta=self.index_path.with_suffix(".meta.json")
        if not self.index_path.exists() or not meta.exists(): raise FileNotFoundError
        self.index=faiss.read_index(str(self.index_path)); self.chunks=json.loads(meta.read_text(encoding="utf-8"))
    def query(self,text,top_k=5):
        if self.index is None:self.load()
        q=self._embed([text]); k=min(top_k,self.index.ntotal)
        scores,idx=self.index.search(q,k)
        return [{**self.chunks[i],"score":float(scores[0][j])} for j,i in enumerate(idx[0]) if i>=0]
