"""One error type for the whole API (PROJECT_SPEC §15.6, SEC-12).

Every error body is {"error": {"code", "message", "request_id"}}: a machine-readable code for
the UI, a plain message, and a request id that also appears in the audit trail. Stack traces
are never sent.
"""

import uuid


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, headers: dict | None = None,
                 details: list | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:6]}"


def error_body(code: str, message: str, request_id: str, details: list | None = None) -> dict:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details:
        body["error"]["details"] = details
    return body
