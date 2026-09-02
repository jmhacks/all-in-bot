#!/usr/bin/env python3
"""Dependency-free MCP server for the All-In speaker-labeled transcript index."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


SERVER_NAME = "all-in-bot"
SERVER_VERSION = "0.1.0"
DEFAULT_INDEX = Path(__file__).resolve().parents[1] / "data/all-in-grok.sqlite3"
MAX_RESULTS = 12
MAX_CONTEXT_TURNS = 3
MAX_CONTEXT_CHARS = 3200
CANONICAL_HOSTS = [
    "Chamath Palihapitiya",
    "Jason Calacanis",
    "David Sacks",
    "David Friedberg",
]
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.-]*")
QUOTED_RE = re.compile(r'["“]([^"”]+)["”]')
STOP_WORDS = {
    "a", "about", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "between", "both", "but", "by", "can", "could", "did", "do",
    "does", "doing", "during", "each", "few", "for", "from", "further",
    "get", "give", "had", "has", "have", "having", "he", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "i", "if", "in",
    "into", "is", "it", "its", "itself", "just", "me", "more", "most",
    "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "out", "over", "own", "same",
    "say", "said", "says", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "think", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "why", "will", "with", "would", "you",
    "your", "yours",
}


def clamp(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if not parts or len(parts) > 3:
        raise ValueError("timestamp must be MM:SS or HH:MM:SS")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("timestamp must contain numbers") from exc
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0]


def _fts_escape(value: str) -> str:
    return value.replace('"', '""')


def build_fts_query(query: str, operator: str = "AND") -> str:
    query = query.strip()
    if not query:
        raise ValueError("query cannot be empty")

    clauses: list[str] = []
    quoted = [match.strip() for match in QUOTED_RE.findall(query) if match.strip()]
    for phrase in quoted[:6]:
        clauses.append(f'"{_fts_escape(phrase)}"')

    without_quotes = QUOTED_RE.sub(" ", query)
    tokens: list[str] = []
    for raw_token in TOKEN_RE.findall(without_quotes):
        token = raw_token.strip(".'’-").lower()
        if not token or token in STOP_WORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    for token in tokens[:18]:
        escaped = _fts_escape(token)
        clauses.append(f'"{escaped}"*' if len(token) >= 4 else f'"{escaped}"')

    if not clauses:
        raw_tokens = TOKEN_RE.findall(query)
        if not raw_tokens:
            raise ValueError("query must contain searchable words")
        clauses = [f'"{_fts_escape(raw_tokens[0])}"']
    if operator not in {"AND", "OR"}:
        raise ValueError("operator must be AND or OR")
    return f"text : ({f' {operator} '.join(clauses)})"


def normalize_date(value: Any, label: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"{label} must use YYYY-MM-DD")
    return text


class TranscriptArchive:
    def __init__(self, index_path: Path | str):
        self.index_path = Path(index_path).expanduser().resolve()
        if not self.index_path.is_file():
            raise FileNotFoundError(
                f"Transcript index not found at {self.index_path}. "
                "Run scripts/build_index.py from the plugin directory."
            )
        uri = f"file:{self.index_path.as_posix()}?mode=ro"
        # The deployed API serves concurrent read-only requests, and FastAPI may
        # execute health checks and handlers on different worker threads.
        self.db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        self.db.close()

    def metadata(self) -> dict[str, str]:
        return {
            row["key"]: row["value"]
            for row in self.db.execute("SELECT key, value FROM metadata")
        }

    def _resolve_speaker(self, requested: str | None) -> str | None:
        if not requested:
            return None
        exact = self.db.execute(
            "SELECT speaker FROM turns WHERE speaker = ? COLLATE NOCASE LIMIT 1",
            (requested,),
        ).fetchone()
        if exact:
            return exact["speaker"]
        candidates = self.db.execute(
            """
            SELECT speaker, COUNT(*) AS turns
            FROM turns
            WHERE speaker LIKE ? COLLATE NOCASE
            GROUP BY speaker
            ORDER BY turns DESC
            LIMIT 3
            """,
            (f"%{requested}%",),
        ).fetchall()
        if len(candidates) == 1:
            return candidates[0]["speaker"]
        if not candidates:
            raise ValueError(f"No indexed speaker matches '{requested}'")
        names = ", ".join(row["speaker"] for row in candidates)
        raise ValueError(f"Speaker '{requested}' is ambiguous. Try one of: {names}")

    @staticmethod
    def _filters(
        speaker: str | None, start_date: str | None, end_date: str | None, alias: str = "t"
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if speaker:
            clauses.append(f"{alias}.speaker = ? COLLATE NOCASE")
            params.append(speaker)
        if start_date:
            clauses.append(f"{alias}.published_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append(f"{alias}.published_date <= ?")
            params.append(end_date)
        return clauses, params

    def _context(self, episode_id: str, turn_index: int, radius: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """
            SELECT turn_index, timestamp, start_seconds, speaker, text
            FROM turns
            WHERE episode_id = ? AND turn_index BETWEEN ? AND ?
            ORDER BY turn_index
            """,
            (episode_id, turn_index - radius, turn_index + radius),
        ).fetchall()
        context: list[dict[str, Any]] = []
        used_chars = 0
        for row in rows:
            remaining = MAX_CONTEXT_CHARS - used_chars
            if remaining <= 0:
                break
            text = row["text"]
            if len(text) > remaining:
                text = text[: max(0, remaining - 1)].rstrip() + "…"
            context.append(
                {
                    "turn_index": row["turn_index"],
                    "timestamp": row["timestamp"],
                    "start_seconds": row["start_seconds"],
                    "speaker": row["speaker"],
                    "text": text,
                    "is_match": row["turn_index"] == turn_index,
                }
            )
            used_chars += len(text)
        return context

    def search_transcripts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        fts_query = build_fts_query(query)
        speaker = self._resolve_speaker(arguments.get("speaker"))
        start_date = normalize_date(arguments.get("start_date"), "start_date")
        end_date = normalize_date(arguments.get("end_date"), "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        limit = clamp(arguments.get("limit"), 1, MAX_RESULTS, 6)
        radius = clamp(arguments.get("context_turns"), 0, MAX_CONTEXT_TURNS, 1)
        filters, filter_params = self._filters(speaker, start_date, end_date)
        where = " AND " + " AND ".join(filters) if filters else ""
        candidate_limit = min(100, max(limit * 6, limit))
        def run_search(active_query: str) -> list[sqlite3.Row]:
            return self.db.execute(
                f"""
                SELECT t.*, bm25(turns_fts, 0.0, 0.0, 2.2) AS fts_rank
                FROM turns_fts
                JOIN turns t ON t.id = turns_fts.rowid
                WHERE turns_fts MATCH ?{where}
                ORDER BY fts_rank, t.published_date DESC
                LIMIT ?
                """,
                [active_query, *filter_params, candidate_limit],
            ).fetchall()

        rows = run_search(fts_query)
        match_mode = "all_terms"
        if not rows:
            fallback_query = build_fts_query(query, operator="OR")
            if fallback_query != fts_query:
                rows = run_search(fallback_query)
                match_mode = "any_term_fallback"

        results: list[dict[str, Any]] = []
        selected: list[tuple[str, int]] = []
        for row in rows:
            if any(
                episode_id == row["episode_id"]
                and abs(turn_index - row["turn_index"]) <= radius * 2 + 1
                for episode_id, turn_index in selected
            ):
                continue
            selected.append((row["episode_id"], row["turn_index"]))
            results.append(
                {
                    "episode_id": row["episode_id"],
                    "episode_title": row["episode_title"],
                    "published_date": row["published_date"],
                    "speaker": row["speaker"],
                    "timestamp": row["timestamp"],
                    "start_seconds": row["start_seconds"],
                    "turn_index": row["turn_index"],
                    "listen_url": row["listen_url"],
                    "context": self._context(row["episode_id"], row["turn_index"], radius),
                }
            )
            if len(results) >= limit:
                break

        return {
            "query": query,
            "match_mode": match_mode,
            "filters": {
                "speaker": speaker,
                "start_date": start_date,
                "end_date": end_date,
            },
            "result_count": len(results),
            "results": results,
            "evidence_note": (
                "Results are ranked transcript passages. Speaker labels and wording can contain "
                "transcription errors. Quote only returned text and cite episode, date, and timestamp."
            ),
        }

    def compare_speakers(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        requested = arguments.get("speakers") or CANONICAL_HOSTS
        if not isinstance(requested, list) or not requested:
            raise ValueError("speakers must be a non-empty list")
        speakers = [str(item) for item in requested[:8]]
        per_speaker = clamp(arguments.get("passages_per_speaker"), 1, 4, 2)
        groups = []
        for requested_speaker in speakers:
            try:
                result = self.search_transcripts(
                    {
                        "query": query,
                        "speaker": requested_speaker,
                        "start_date": arguments.get("start_date"),
                        "end_date": arguments.get("end_date"),
                        "limit": per_speaker,
                        "context_turns": arguments.get("context_turns", 1),
                    }
                )
                groups.append(
                    {
                        "speaker": result["filters"]["speaker"],
                        "result_count": result["result_count"],
                        "results": result["results"],
                    }
                )
            except ValueError as exc:
                groups.append(
                    {"speaker": requested_speaker, "result_count": 0, "results": [], "note": str(exc)}
                )
        return {
            "query": query,
            "start_date": normalize_date(arguments.get("start_date"), "start_date"),
            "end_date": normalize_date(arguments.get("end_date"), "end_date"),
            "speakers": groups,
            "comparison_note": (
                "Compare only what this evidence supports. A missing result is an evidence gap, "
                "not proof that a speaker never discussed the subject."
            ),
        }

    def trace_topic(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        fts_query = build_fts_query(query)
        speaker = self._resolve_speaker(arguments.get("speaker"))
        start_date = normalize_date(arguments.get("start_date"), "start_date")
        end_date = normalize_date(arguments.get("end_date"), "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        bucket = str(arguments.get("bucket") or "year").lower()
        if bucket not in {"year", "quarter"}:
            raise ValueError("bucket must be 'year' or 'quarter'")
        bucket_column = "year" if bucket == "year" else "quarter"
        filters, filter_params = self._filters(speaker, start_date, end_date)
        where = " AND " + " AND ".join(filters) if filters else ""

        matches = self.db.execute(
            f"""
            SELECT CAST(t.{bucket_column} AS TEXT) AS period,
                   COUNT(*) AS matching_turns,
                   COUNT(DISTINCT t.episode_id) AS matching_episodes
            FROM turns_fts
            JOIN turns t ON t.id = turns_fts.rowid
            WHERE turns_fts MATCH ?{where}
            GROUP BY t.{bucket_column}
            ORDER BY t.{bucket_column}
            """,
            [fts_query, *filter_params],
        ).fetchall()
        total_filters, total_params = self._filters(speaker, start_date, end_date, alias="turns")
        total_where = " WHERE " + " AND ".join(total_filters) if total_filters else ""
        totals = {
            row["period"]: row
            for row in self.db.execute(
                f"""
                SELECT CAST({bucket_column} AS TEXT) AS period,
                       SUM(word_count) AS corpus_words,
                       COUNT(*) AS corpus_turns,
                       COUNT(DISTINCT episode_id) AS corpus_episodes
                FROM turns{total_where}
                GROUP BY {bucket_column}
                ORDER BY {bucket_column}
                """,
                total_params,
            ).fetchall()
        }
        series = []
        for row in matches:
            total = totals[row["period"]]
            corpus_words = int(total["corpus_words"] or 0)
            series.append(
                {
                    "period": row["period"],
                    "matching_turns": row["matching_turns"],
                    "matching_episodes": row["matching_episodes"],
                    "corpus_words": corpus_words,
                    "matching_turns_per_100k_words": round(
                        row["matching_turns"] * 100000 / corpus_words, 2
                    ) if corpus_words else 0,
                }
            )

        examples_per_period = clamp(arguments.get("examples_per_period"), 0, 2, 1)
        if examples_per_period:
            for item in series:
                if bucket == "year":
                    period_start = f"{item['period']}-01-01"
                    period_end = f"{item['period']}-12-31"
                else:
                    year_text, quarter_text = item["period"].split("-Q")
                    quarter_number = int(quarter_text)
                    start_month = (quarter_number - 1) * 3 + 1
                    end_month = start_month + 2
                    period_start = f"{year_text}-{start_month:02d}-01"
                    end_day = 31 if end_month in {1, 3, 5, 7, 8, 10, 12} else 30
                    if end_month == 2:
                        end_day = 29
                    period_end = f"{year_text}-{end_month:02d}-{end_day:02d}"
                effective_start = max(filter(None, [start_date, period_start]))
                effective_end = min(filter(None, [end_date, period_end]))
                evidence = self.search_transcripts(
                    {
                        "query": query,
                        "speaker": speaker,
                        "start_date": effective_start,
                        "end_date": effective_end,
                        "limit": examples_per_period,
                        "context_turns": 0,
                    }
                )
                item["examples"] = evidence["results"]

        return {
            "query": query,
            "bucket": bucket,
            "speaker": speaker,
            "start_date": start_date,
            "end_date": end_date,
            "series": series,
            "measurement_note": (
                "The rate is matching transcript turns per 100,000 words in the selected corpus, "
                "not sentiment, approval, or raw phrase occurrences."
            ),
        }

    def get_episode_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(arguments.get("episode_id") or "").strip()
        if not episode_id:
            raise ValueError("episode_id is required")
        episode = self.db.execute(
            "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if not episode:
            raise ValueError(f"Unknown episode_id '{episode_id}'")
        before = clamp(arguments.get("before_turns"), 0, 4, 2)
        after = clamp(arguments.get("after_turns"), 0, 4, 2)
        if arguments.get("turn_index") is not None:
            target = self.db.execute(
                "SELECT turn_index FROM turns WHERE episode_id = ? AND turn_index = ?",
                (episode_id, int(arguments["turn_index"])),
            ).fetchone()
        elif arguments.get("timestamp") is not None:
            seconds = parse_timestamp(str(arguments["timestamp"]))
            target = self.db.execute(
                """
                SELECT turn_index
                FROM turns
                WHERE episode_id = ?
                ORDER BY ABS(start_seconds - ?)
                LIMIT 1
                """,
                (episode_id, seconds),
            ).fetchone()
        else:
            raise ValueError("provide turn_index or timestamp")
        if not target:
            raise ValueError("No transcript turn found near that location")
        turn_index = int(target["turn_index"])
        rows = self.db.execute(
            """
            SELECT turn_index, timestamp, start_seconds, speaker, text
            FROM turns
            WHERE episode_id = ? AND turn_index BETWEEN ? AND ?
            ORDER BY turn_index
            """,
            (episode_id, turn_index - before, turn_index + after),
        ).fetchall()
        excerpt = []
        used_chars = 0
        for row in rows:
            remaining = MAX_CONTEXT_CHARS - used_chars
            if remaining <= 0:
                break
            text = row["text"]
            if len(text) > remaining:
                text = text[: max(0, remaining - 1)].rstrip() + "…"
            excerpt.append(
                {
                    "turn_index": row["turn_index"],
                    "timestamp": row["timestamp"],
                    "start_seconds": row["start_seconds"],
                    "speaker": row["speaker"],
                    "text": text,
                    "is_target": row["turn_index"] == turn_index,
                }
            )
            used_chars += len(text)
        return {
            "episode_id": episode["episode_id"],
            "episode_number": episode["episode_number"],
            "episode_title": episode["title"],
            "published_date": episode["published_date"],
            "listen_url": episode["listen_url"],
            "target_turn_index": turn_index,
            "context": excerpt,
            "content_note": "This is a bounded excerpt, not a full transcript.",
        }

    def list_speakers(self, arguments: dict[str, Any]) -> dict[str, Any]:
        minimum_turns = clamp(arguments.get("minimum_turns"), 1, 10000, 5)
        limit = clamp(arguments.get("limit"), 1, 100, 30)
        rows = self.db.execute(
            """
            SELECT speaker, COUNT(*) AS turns, COUNT(DISTINCT episode_id) AS episodes,
                   MIN(published_date) AS first_date, MAX(published_date) AS last_date
            FROM turns
            GROUP BY speaker
            HAVING COUNT(*) >= ?
            ORDER BY turns DESC
            LIMIT ?
            """,
            (minimum_turns, limit),
        ).fetchall()
        return {
            "speaker_count": len(rows),
            "speakers": [dict(row) for row in rows],
            "note": "Names come from transcript labels and may include unresolved diarization labels.",
        }

    def get_corpus_stats(self, arguments: dict[str, Any]) -> dict[str, Any]:
        metadata = self.metadata()
        top_speakers = self.list_speakers({"minimum_turns": 50, "limit": 12})["speakers"]
        return {
            "source": metadata.get("source_name"),
            "generated_at": metadata.get("generated_at"),
            "episodes": int(metadata.get("episode_count", 0)),
            "turns": int(metadata.get("turn_count", 0)),
            "words": int(metadata.get("word_count", 0)),
            "start_date": metadata.get("start_date"),
            "end_date": metadata.get("end_date"),
            "top_speakers": top_speakers,
            "limitations": [
                "Automated transcript wording and speaker attribution can contain errors.",
                "Archive search results are evidence passages, not a substitute for full context.",
                "Topic counts measure attention, not endorsement or sentiment.",
            ],
        }


TOOL_DEFINITIONS = [
    {
        "name": "search_transcripts",
        "description": (
            "Search the All-In Podcast transcript archive for ranked, citation-ready passages. "
            "Use this before making claims about what was said."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic, phrase, claim, person, or event."},
                "speaker": {"type": "string", "description": "Optional exact or unambiguous speaker name."},
                "start_date": {"type": "string", "description": "Optional YYYY-MM-DD lower bound."},
                "end_date": {"type": "string", "description": "Optional YYYY-MM-DD upper bound."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": 6},
                "context_turns": {
                    "type": "integer", "minimum": 0, "maximum": MAX_CONTEXT_TURNS, "default": 1
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "compare_speakers",
        "description": "Retrieve balanced evidence for how multiple All-In speakers discuss the same subject.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "speakers": {
                    "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "passages_per_speaker": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
                "context_turns": {"type": "integer", "minimum": 0, "maximum": 3, "default": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "trace_topic",
        "description": (
            "Measure transcript attention to a topic by year or quarter and return representative evidence. "
            "The measure is matching turns per 100,000 corpus words, not sentiment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "speaker": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "bucket": {"type": "string", "enum": ["year", "quarter"], "default": "year"},
                "examples_per_period": {"type": "integer", "minimum": 0, "maximum": 2, "default": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_episode_context",
        "description": "Get a short transcript window around a known episode timestamp or turn index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_id": {"type": "string"},
                "timestamp": {"type": "string", "description": "MM:SS or HH:MM:SS."},
                "turn_index": {"type": "integer", "minimum": 0},
                "before_turns": {"type": "integer", "minimum": 0, "maximum": 4, "default": 2},
                "after_turns": {"type": "integer", "minimum": 0, "maximum": 4, "default": 2},
            },
            "required": ["episode_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_speakers",
        "description": "List indexed transcript speaker labels and their archive coverage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "minimum_turns": {"type": "integer", "minimum": 1, "default": 5},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_corpus_stats",
        "description": "Return source coverage, index freshness, and major corpus limitations.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class McpServer:
    def __init__(self, archive: TranscriptArchive):
        self.archive = archive
        self.handlers = {
            "search_transcripts": archive.search_transcripts,
            "compare_speakers": archive.compare_speakers,
            "trace_topic": archive.trace_topic,
            "get_episode_context": archive.get_episode_context,
            "list_speakers": archive.list_speakers,
            "get_corpus_stats": archive.get_corpus_stats,
        }

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            return None
        if method == "initialize":
            client_version = (request.get("params") or {}).get("protocolVersion")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": client_version or "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "Search before answering archive-specific questions. Cite speaker, episode, date, "
                        "and timestamp. Return only short excerpts, never full transcripts."
                    ),
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_DEFINITIONS}}
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            handler = self.handlers.get(name)
            if not handler:
                return self._error(request_id, -32602, f"Unknown tool '{name}'")
            try:
                payload = handler(params.get("arguments") or {})
            except (ValueError, TypeError, sqlite3.Error) as exc:
                error_payload = {"error": str(exc), "tool": name}
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(error_payload)}],
                        "structuredContent": error_payload,
                        "isError": True,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
                    ],
                    "structuredContent": payload,
                    "isError": False,
                },
            }
        return self._error(request_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def iter_requests(stream: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in stream:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON input: {exc}", file=sys.stderr, flush=True)
            continue
        if isinstance(payload, dict):
            yield payload


def main() -> None:
    index_path = Path(os.environ.get("ALL_IN_BOT_INDEX") or DEFAULT_INDEX)
    try:
        archive = TranscriptArchive(index_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    server = McpServer(archive)
    try:
        for request in iter_requests(sys.stdin):
            response = server.handle(request)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        archive.close()


if __name__ == "__main__":
    main()
