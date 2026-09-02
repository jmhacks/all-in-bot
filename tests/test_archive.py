from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/all-in-grok.sqlite3"
sys.path.insert(0, str(ROOT))

from server.all_in_mcp import McpServer, TranscriptArchive, build_fts_query  # noqa: E402
from api.mcp import authorized, valid_origin  # noqa: E402

try:
    from fastapi.testclient import TestClient
    from railway_app import app
except ImportError:
    TestClient = None
    app = None


@unittest.skipUnless(INDEX.is_file(), "private transcript index has not been built")
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.archive = TranscriptArchive(INDEX)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.archive.close()

    def test_stats_match_built_corpus(self) -> None:
        result = self.archive.get_corpus_stats({})
        self.assertEqual(result["episodes"], 406)
        self.assertEqual(result["turns"], 102062)
        self.assertGreater(result["words"], 5_000_000)
        self.assertEqual(result["start_date"], "2020-03-15")
        self.assertEqual(result["end_date"], "2026-08-29")

    def test_search_is_transcript_text_scoped(self) -> None:
        result = self.archive.search_transcripts(
            {"query": "tariffs", "start_date": "2025-01-01", "limit": 5, "context_turns": 0}
        )
        self.assertEqual(result["match_mode"], "all_terms")
        self.assertEqual(result["result_count"], 5)
        for passage in result["results"]:
            matched = next(item for item in passage["context"] if item["is_match"])
            self.assertIn("tariff", matched["text"].lower())
            self.assertTrue(passage["listen_url"].startswith("https://podcasts.apple.com/"))

    def test_speaker_comparison_is_grouped(self) -> None:
        result = self.archive.compare_speakers(
            {
                "query": "nuclear energy",
                "speakers": ["Chamath", "David Friedberg"],
                "passages_per_speaker": 1,
            }
        )
        self.assertEqual([group["speaker"] for group in result["speakers"]], [
            "Chamath Palihapitiya",
            "David Friedberg",
        ])
        self.assertTrue(all(group["result_count"] == 1 for group in result["speakers"]))

    def test_topic_trace_has_real_denominator(self) -> None:
        result = self.archive.trace_topic(
            {"query": "tariffs", "bucket": "year", "examples_per_period": 0}
        )
        row_2025 = next(row for row in result["series"] if row["period"] == "2025")
        self.assertGreater(row_2025["matching_turns"], 0)
        self.assertGreater(row_2025["corpus_words"], 1_000_000)
        expected = round(row_2025["matching_turns"] * 100000 / row_2025["corpus_words"], 2)
        self.assertEqual(row_2025["matching_turns_per_100k_words"], expected)

    def test_episode_context_is_bounded(self) -> None:
        result = self.archive.get_episode_context(
            {"episode_id": "1000468436014", "timestamp": "0:10", "before_turns": 1, "after_turns": 1}
        )
        self.assertLessEqual(len(result["context"]), 3)
        self.assertTrue(any(item["is_target"] for item in result["context"]))

    def test_mcp_tool_list(self) -> None:
        response = McpServer(self.archive).handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(
            names,
            {
                "search_transcripts",
                "compare_speakers",
                "trace_topic",
                "get_episode_context",
                "list_speakers",
                "get_corpus_stats",
            },
        )


class QueryTests(unittest.TestCase):
    def test_query_uses_text_column_and_all_terms(self) -> None:
        query = build_fts_query("sovereign AI")
        self.assertTrue(query.startswith("text : ("))
        self.assertIn(" AND ", query)

    def test_http_origin_policy(self) -> None:
        self.assertTrue(valid_origin(None))
        self.assertTrue(valid_origin("https://app.cursor.com"))
        self.assertTrue(valid_origin("http://localhost:3000"))
        self.assertFalse(valid_origin("https://attacker.example"))

    def test_optional_http_bearer_token(self) -> None:
        old_value = os.environ.get("ALL_IN_GROK_TOKEN")
        try:
            os.environ["ALL_IN_GROK_TOKEN"] = "test-secret"
            self.assertTrue(authorized("Bearer test-secret"))
            self.assertFalse(authorized("Bearer wrong"))
            self.assertFalse(authorized(None))
        finally:
            if old_value is None:
                os.environ.pop("ALL_IN_GROK_TOKEN", None)
            else:
                os.environ["ALL_IN_GROK_TOKEN"] = old_value


@unittest.skipUnless(INDEX.is_file(), "private transcript index has not been built")
class ProtocolTests(unittest.TestCase):
    def test_stdio_initialize_and_tool_call(self) -> None:
        env = os.environ.copy()
        env["ALL_IN_BOT_INDEX"] = str(INDEX)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server/all_in_mcp.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_corpus_stats", "arguments": {}},
            },
        ]
        payload = "".join(json.dumps(item) + "\n" for item in requests)
        stdout, stderr = process.communicate(payload, timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        responses = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "all-in-bot")
        self.assertEqual(responses[1]["result"]["structuredContent"]["episodes"], 406)


@unittest.skipUnless(INDEX.is_file() and TestClient is not None, "HTTP test dependencies unavailable")
class HttpMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_healthcheck(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["episodes"], 406)

    def test_stateless_mcp_request(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "get_corpus_stats", "arguments": {}},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["structuredContent"]["turns"], 102062)

    def test_private_token(self) -> None:
        with patch.dict(os.environ, {"ALL_IN_GROK_TOKEN": "private-test"}):
            denied = self.client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            )
            allowed = self.client.post(
                "/mcp",
                headers={"Authorization": "Bearer private-test"},
                json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
            )
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
