#!/usr/bin/env python3
"""Verify a deployed All-In Bot Streamable HTTP MCP endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def call(url: str, payload: dict) -> dict:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Full endpoint URL, for example https://example.vercel.app/api/mcp")
    args = parser.parse_args()
    initialize = call(
        args.url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    stats = call(
        args.url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_corpus_stats", "arguments": {}},
        },
    )
    search = call(
        args.url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_transcripts", "arguments": {"query": "sovereign AI", "limit": 2}},
        },
    )
    result = {
        "server": initialize["result"]["serverInfo"],
        "episodes": stats["result"]["structuredContent"]["episodes"],
        "search_results": search["result"]["structuredContent"]["result_count"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
