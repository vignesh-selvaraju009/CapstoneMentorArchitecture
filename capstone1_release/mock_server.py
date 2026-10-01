"""Minimal in-memory mock REST API for the "Employees" endpoint used by the
generated test suite, so generated pytest/Postman tests have a real, reachable
server to call instead of a placeholder/unreachable Base URL.

Implements GET/PATCH/DELETE /employees/{employeeId} with simple auth and
existence checks. Not a full OpenAPI-driven mock - just enough REST semantics
(401 for missing/expired auth, 404 for unknown ids, 200/204 for success) to
demonstrate the generated test suite exercising real HTTP responses.

Run: python mock_server.py [port]   (default port 5055)
Uses only the Python standard library - no extra dependencies required.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

Employee = dict[str, Any]

SEED_EMPLOYEES: dict[int, Employee] = {
    1: {"id": 1, "name": "Alice Example", "email": "alice@example.com", "role": "employee"},
    2: {"id": 2, "name": "Bob Example", "email": "bob@example.com", "role": "employee"},
}
employees: dict[int, Employee] = {k: dict(v) for k, v in SEED_EMPLOYEES.items()}

_PATH_RE = re.compile(r"^/employees/([^/?]+)")


class EmployeesHandler(BaseHTTPRequestHandler):
    def _reset_state(self) -> None:
        # Each generated test makes exactly one request and expects a fresh,
        # independent server state (no shared mutation across test files).
        global employees
        employees = {k: dict(v) for k, v in SEED_EMPLOYEES.items()}

    def _employee_id(self) -> int | None:
        match = _PATH_RE.match(self.path)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
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
        emp_id = self._employee_id()
        employee = employees.get(emp_id) if emp_id is not None else None
        if employee is None:
            self._send_json(404, {"error": "employee not found"})
            return
        self._send_json(200, employee)

    def do_PATCH(self) -> None:  # noqa: N802
        self._reset_state()
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        emp_id = self._employee_id()
        if emp_id is None or emp_id not in employees:
            self._send_json(404, {"error": "employee not found"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b""
        updates: dict[str, Any] = {}
        if raw_body:
            try:
                updates = json.loads(raw_body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid JSON body"})
                return
        for restricted in ("role", "isAdmin", "is_admin"):
            updates.pop(restricted, None)
        employees[emp_id].update(updates)
        self._send_json(200, employees[emp_id])

    def do_DELETE(self) -> None:  # noqa: N802
        self._reset_state()
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        emp_id = self._employee_id()
        if emp_id is None or emp_id not in employees:
            self._send_json(404, {"error": "employee not found"})
            return
        del employees[emp_id]
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # keep console output clean


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5055
    server = ThreadingHTTPServer(("127.0.0.1", port), EmployeesHandler)
    print(f"Mock Employees API running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
