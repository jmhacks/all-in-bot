"""Railway and Render entrypoint for the stateless All-In Bot HTTP MCP server."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from api.mcp import MAX_BODY_BYTES, authorized, get_archive, handle_payload, valid_origin


app = FastAPI(
    title="All-In Bot MCP",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def no_store_json(payload: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/healthz")
def healthz() -> JSONResponse:
    try:
        metadata = get_archive().metadata()
    except (FileNotFoundError, OSError) as exc:
        return no_store_json({"status": "error", "error": str(exc)}, status_code=503)
    return no_store_json(
        {
            "status": "ok",
            "service": "all-in-bot",
            "episodes": int(metadata.get("episode_count", 0)),
            "turns": int(metadata.get("turn_count", 0)),
            "start_date": metadata.get("start_date"),
            "end_date": metadata.get("end_date"),
        }
    )


@app.get("/mcp")
@app.delete("/mcp")
def unsupported_mcp_stream() -> Response:
    return Response(status_code=405, headers={"Allow": "POST", "Cache-Control": "no-store"})


@app.post("/mcp")
async def mcp(request: Request) -> Response:
    if not valid_origin(request.headers.get("origin")):
        return no_store_json({"error": "Origin is not allowed"}, status_code=403)
    if not authorized(request.headers.get("authorization")):
        return no_store_json({"error": "Unauthorized"}, status_code=401)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return no_store_json({"error": "Request body is too large"}, status_code=413)
        except ValueError:
            return no_store_json({"error": "Invalid Content-Length"}, status_code=400)
    body = await request.body()
    if not body or len(body) > MAX_BODY_BYTES:
        return no_store_json({"error": "Request body is empty or too large"}, status_code=413)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return no_store_json({"error": "Request body must be one JSON-RPC object"}, status_code=400)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not payload.get("method"):
        return no_store_json({"error": "Invalid JSON-RPC request"}, status_code=400)
    try:
        result = handle_payload(payload)
    except (FileNotFoundError, OSError) as exc:
        return no_store_json({"error": str(exc)}, status_code=503)
    if result is None:
        return Response(status_code=202, headers={"Cache-Control": "no-store"})
    return no_store_json(result)
