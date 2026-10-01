from __future__ import annotations
import json
import logging
import sqlite3
from datetime import datetime,timezone
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from config import settings

logger = logging.getLogger(__name__)
LOCAL_DOCUMENT_STORE_PATH = settings.storage_dir / "ingested_documents.sqlite3"

class MongoDocumentRepository:
    def __init__(self,uri=None,database=None,collection=None,chunk_collection=None):
        self._using_local = not (settings.mongo_uri or uri)
        self.client = None
        self.database = None
        self.collection = None
        self.chunk_collection = None
        if self._using_local:
            self._initialize_local_store()
            return
        self.client=MongoClient(uri or settings.mongo_uri,serverSelectionTimeoutMS=5000)
        self.database=self.client[database or settings.mongo_database]
        self.collection=self.database[collection or settings.mongo_document_collection]
        self.chunk_collection=self.database[chunk_collection or settings.mongo_chunk_collection]

    def _initialize_local_store(self):
        LOCAL_DOCUMENT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(document_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS chunks "
                "(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
        self._using_local = True

    def ping(self):
        if self._using_local:
            return True
        try:
            self.client.admin.command("ping")
        except ServerSelectionTimeoutError:
            logger.warning(
                "MongoDB is unavailable; using local document store at %s",
                LOCAL_DOCUMENT_STORE_PATH,
            )
            self._initialize_local_store()
        return True

    def save_document(self,document_id,filename,document_type,raw,normalized,classification):
        document={"document_id":document_id,"file_name":filename,"document_type":document_type,"classification":classification,"raw":raw,"normalized":normalized,"ingested_at":datetime.now(timezone.utc).isoformat()}
        if self._using_local:
            with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO documents (document_id, payload) VALUES (?, ?)",
                    (document_id, json.dumps(document, ensure_ascii=False)),
                )
            return
        self.collection.replace_one({"document_id":document_id},document,upsert=True)

    def save_chunks(self,chunks):
        if chunks:
            if self._using_local:
                document_id = chunks[0]["document_id"]
                with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
                    connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                    connection.executemany(
                        "INSERT OR REPLACE INTO chunks (chunk_id, document_id, payload) VALUES (?, ?, ?)",
                        [
                            (chunk["chunk_id"], document_id, json.dumps(chunk, ensure_ascii=False))
                            for chunk in chunks
                        ],
                    )
                return
            self.chunk_collection.delete_many({"document_id":chunks[0]["document_id"]}); self.chunk_collection.insert_many(chunks)

    def get_document(self,document_id):
        if self._using_local:
            with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
                row = connection.execute(
                    "SELECT payload FROM documents WHERE document_id = ?", (document_id,)
                ).fetchone()
            return json.loads(row[0]) if row else None
        return self.collection.find_one({"document_id":document_id},{"_id":0})

    def get_chunks(self,document_id):
        if self._using_local:
            with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
                rows = connection.execute(
                    "SELECT payload FROM chunks WHERE document_id = ? ORDER BY rowid", (document_id,)
                ).fetchall()
            return [json.loads(row[0]) for row in rows]
        return list(self.chunk_collection.find({"document_id":document_id},{"_id":0}))

    def get_all_chunks(self):
        if self._using_local:
            with sqlite3.connect(LOCAL_DOCUMENT_STORE_PATH) as connection:
                rows = connection.execute("SELECT payload FROM chunks ORDER BY rowid").fetchall()
            return [json.loads(row[0]) for row in rows]
        return list(self.chunk_collection.find({}, {"_id":0}))
class DocumentUnderstandingTool:
    def __init__(self,repository): self.repository=repository
    def understand(self,document_id):
        doc=self.repository.get_document(document_id)
        if not doc: raise KeyError(document_id)
        return {"document_id":document_id,"document_type":doc.get("document_type"),"classification":doc.get("classification"),"common_parameters":doc.get("normalized"),"chunks":self.repository.get_chunks(document_id)}
