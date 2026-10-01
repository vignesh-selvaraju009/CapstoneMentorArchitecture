# Mentor-driven architecture changes

## Two upload flows

- **Data Ingestion**: reusable knowledge/backend documents -> classification -> MongoDB -> structure-aware chunks -> embeddings/vector index.
- **Test Case Generator**: API specification -> parser -> MongoDB document understanding/common parameter model -> test-case generation.

## Common document model

The downstream test-case layer receives a fixed contract. Document-specific values are populated dynamically from the uploaded source. Field definitions and aliases live in `config/ingestion_config.json`, not in UI code.

## Chunking

The ingestion chunker is structure-aware. Each chunk carries `document_id`, `chunk_id`, `parent_chunk_id`, `path`, and `kind` so relationships can be reconstructed during retrieval.

## MongoDB document-understanding tool

`ingestion/mongo_document_tool.py` provides a repository plus `DocumentUnderstandingTool`. The tool reads a selected MongoDB collection and returns the normalized common parameters and related chunks.

## Embeddings

The embedding provider/model is configuration-driven in `config/ingestion_config.json` and can be changed without modifying application code. The initial configured model is `BAAI/bge-small-en-v1.5`; it should be evaluated against the project's retrieval dataset before being treated as final.

## Configuration

MongoDB connection details, collection names, parser mappings, classification rules, chunking parameters, embedding model, and common-schema mappings are externalized.

## Tests

`tests/` (plus root-level `conftest.py`) covers document parsing/classification, structure-aware chunking and relationship reconstruction, the common document model (both OpenAPI and generic documents), the MongoDB repository/document-understanding tool (via `mongomock`, no real server required), the configurable embedding/vector-store abstraction (via a deterministic fake embedding model, no network access required), the existing OpenAPI parser, coverage/duplicate validators, and the legacy dataset-ingestion flow. `tests/test_end_to_end_pipeline.py` traces a real sample (`samples/petstore.yaml`) through the entire pipeline. Run with `py -m pytest tests -q` from `capstone1_release/`.

## Known limitations

- `ingestion/document_parser.py` treats `.pdf`/`.docx` as plain-text sources (`Path.read_text`), which will not correctly extract binary PDF/DOCX content. Real extraction would need an added dependency (e.g. `pypdf`, `python-docx`) — not yet wired in.
- The chunker's relationship metadata was fixed during this pass: large objects that exceed `max_characters` now emit a lightweight `object_anchor` chunk so their children carry a real, resolvable `parent_chunk_id` (previously the anchor was always `None`, meaning relationships were unrecoverable for any oversized document).
- Integration tests use `mongomock`/a fake embedding model; they do not verify behavior against a live MongoDB instance or the real `BAAI/bge-small-en-v1.5` model download.
