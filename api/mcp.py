"""Stateless Streamable HTTP transport for the All-In Bot MCP server."""

from __future__ import annotations

import gzip
import hmac
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server.all_in_mcp import McpServer, TranscriptArchive


ROOT = Path(__file__).resolve().parents[1]
COMPRESSED_INDEX = ROOT / "data/all-in-grok.sqlite3.gz"
RUNTIME_INDEX = Path("/tmp/all-in-grok.sqlite3")
MAX_BODY_BYTES = 64 * 1024
_archive: TranscriptArchive | None = None
_archive_lock = threading.Lock()


def valid_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    return (
        hostname == "cursor.com"
        or hostname.endswith(".cursor.com")
        or hostname in {"localhost", "127.0.0.1"}
    )


def authorized(header: str | None) -> bool:
    expected = os.environ.get("ALL_IN_GROK_TOKEN")
    if not expected:
        return True
    if not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header.removeprefix("Bearer "), expected)


def prepare_runtime_index() -> Path:
    if RUNTIME_INDEX.is_file() and RUNTIME_INDEX.stat().st_size > 1_000_000:
        return RUNTIME_INDEX
    if not COMPRESSED_INDEX.is_file():
        raise FileNotFoundError(
            "Missing data/all-in-grok.sqlite3.gz. Run scripts/prepare_deployment.py before deployment."
        )
    temporary = RUNTIME_INDEX.with_suffix(".building")
    with gzip.open(COMPRESSED_INDEX, "rb") as source, temporary.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    os.replace(temporary, RUNTIME_INDEX)
    return RUNTIME_INDEX


def get_archive() -> TranscriptArchive:
    global _archive
    if _archive is not None:
        return _archive
    with _archive_lock:
        if _archive is None:
            _archive = TranscriptArchive(prepare_runtime_index())
    return _archive


def handle_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    return McpServer(get_archive()).handle(payload)


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self) -> None:  # noqa: N802
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if not valid_origin(self.headers.get("Origin")):
            self._send_json(403, {"error": "Origin is not allowed"})
            return
        if not authorized(self.headers.get("Authorization")):
            self._send_json(401, {"error": "Unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "Request body is empty or too large"})
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be one JSON-RPC object"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be one JSON-RPC object"})
            return
        if payload.get("jsonrpc") != "2.0" or not payload.get("method"):
            self._send_json(400, {"error": "Invalid JSON-RPC request"})
            return
        try:
            response = handle_payload(payload)
        except (FileNotFoundError, OSError) as exc:
            self._send_json(503, {"error": str(exc)})
            return
        if response is None:
            self._send_empty(202)
            return
        self._send_json(200, response)


__all__ = ["authorized", "get_archive", "handle_payload", "handler", "prepare_runtime_index", "valid_origin"]
