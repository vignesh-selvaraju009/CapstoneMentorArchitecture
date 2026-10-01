"""Minimal in-memory mock REST API for samples/petstore.yaml, so generated
pytest/Postman tests have a real, reachable server to call instead of a
placeholder/unreachable Base URL.

Implements GET/POST /pets and GET/DELETE /pets/{petId} with simple auth and
existence checks (401 for missing/expired auth on protected routes, 404 for
unknown ids, 200/201/204 for success). Not a full OpenAPI-driven mock - just
enough REST semantics to demonstrate the generated test suite exercising
real HTTP responses.

Run: python mock_petstore_server.py [port]   (default port 5056)
Uses only the Python standard library - no extra dependencies required.
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TypeAlias, cast
from urllib.parse import parse_qs, urlsplit

Pet: TypeAlias = dict[str, Any]

SEED_PETS: dict[int, Pet] = {
    1: {"id": 1, "name": "Fido", "tag": "dog"},
    2: {"id": 2, "name": "Whiskers", "tag": "cat"},
}
_pets: dict[int, Pet] = {k: dict(v) for k, v in SEED_PETS.items()}
_next_id = max(SEED_PETS) + 1

_PET_ID_RE = re.compile(r"^/pets/([^/?]+)/?$")


class PetsHandler(BaseHTTPRequestHandler):
    def _reset_state(self) -> None:
        # Each generated test makes exactly one request and expects a fresh,
        # independent server state (no shared mutation across test files).
        global _next_id, _pets
        _pets = {k: dict(v) for k, v in SEED_PETS.items()}
        _next_id = max(SEED_PETS) + 1

    def _pet_id(self) -> int | None:
        match = _PET_ID_RE.match(urlsplit(self.path).path)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth:
            return False
        if auth.strip() == "Bearer expired.invalid.token":
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        self._reset_state()
        split = urlsplit(self.path)
        if split.path == "/pets":
            query = parse_qs(split.query)
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                self._send_json(400, {"code": 400, "message": "invalid limit"})
                return
            if limit < 0:
                self._send_json(400, {"code": 400, "message": "invalid limit"})
                return
            pets = list(_pets.values())[:limit]
            self._send_json(200, pets)
            return

        pet_id = self._pet_id()
        pet = _pets.get(pet_id) if pet_id is not None else None
        if pet is None:
            self._send_json(404, {"code": 404, "message": "pet not found"})
            return
        self._send_json(200, pet)

    def do_POST(self) -> None:  # noqa: N802
        self._reset_state()
        global _next_id
        if not self._authorized():
            self._send_json(401, {"code": 401, "message": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b""
        try:
            parsed_body: Any = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"code": 400, "message": "invalid JSON body"})
            return
        if not isinstance(parsed_body, dict):
            self._send_json(400, {"code": 400, "message": "name is required"})
            return
        body = cast(dict[str, Any], parsed_body)
        if not body.get("name"):
            self._send_json(400, {"code": 400, "message": "name is required"})
            return
        pet: Pet = {"id": _next_id, "name": body["name"], "tag": body.get("tag")}
        _pets[_next_id] = pet
        _next_id += 1
        self._send_json(201, pet)

    def do_DELETE(self) -> None:  # noqa: N802
        self._reset_state()
        if not self._authorized():
            self._send_json(401, {"code": 401, "message": "unauthorized"})
            return
        pet_id = self._pet_id()
        if pet_id is None or pet_id not in _pets:
            self._send_json(404, {"code": 404, "message": "pet not found"})
            return
        del _pets[pet_id]
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep console output clean


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5056
    server = ThreadingHTTPServer(("127.0.0.1", port), PetsHandler)
    print(f"Mock Petstore API running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
