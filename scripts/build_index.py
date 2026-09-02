#!/usr/bin/env python3
"""Build the private SQLite FTS5 index used by the All-In Bot plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPASS_ROOT = PLUGIN_ROOT.parent / "all-in-summit-compass"
DEFAULT_TURNS = DEFAULT_COMPASS_ROOT / "corpus/spoken/normalized/turns.jsonl"
DEFAULT_EPISODES = DEFAULT_COMPASS_ROOT / "corpus/spoken/normalized/episodes.json"
DEFAULT_LINKS = DEFAULT_COMPASS_ROOT / "scripts/listening-links.json"
DEFAULT_OUTPUT = PLUGIN_ROOT / "data/all-in-grok.sqlite3"
WORD_RE = re.compile(r"\b[\w]+(?:[’'][\w]+)?\b", re.UNICODE)
EPISODE_NUMBER_RE = re.compile(r"^E(\d+)\b", re.IGNORECASE)


SCHEMA = """
PRAGMA page_size = 4096;
CREATE TABLE metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE episodes (
  episode_id TEXT PRIMARY KEY,
  episode_number INTEGER,
  title TEXT NOT NULL,
  published_at TEXT NOT NULL,
  published_date TEXT NOT NULL,
  source_file TEXT,
  turn_count INTEGER NOT NULL,
  word_count INTEGER NOT NULL,
  listen_url TEXT
);
CREATE TABLE turns (
  id INTEGER PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
  episode_title TEXT NOT NULL,
  published_at TEXT NOT NULL,
  published_date TEXT NOT NULL,
  year INTEGER NOT NULL,
  quarter TEXT NOT NULL,
  turn_index INTEGER NOT NULL,
  timestamp TEXT NOT NULL,
  start_seconds REAL NOT NULL,
  speaker TEXT NOT NULL,
  canonical_host TEXT,
  attribution_status TEXT,
  text TEXT NOT NULL,
  word_count INTEGER NOT NULL,
  listen_url TEXT
);
CREATE INDEX turns_episode_turn_idx ON turns(episode_id, turn_index);
CREATE INDEX turns_speaker_date_idx ON turns(speaker, published_date);
CREATE INDEX turns_date_idx ON turns(published_date);
CREATE INDEX turns_year_idx ON turns(year);
CREATE INDEX turns_quarter_idx ON turns(quarter);
CREATE VIRTUAL TABLE turns_fts USING fts5(
  episode_title,
  speaker,
  text,
  content='turns',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=Path, default=DEFAULT_TURNS)
    parser.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    parser.add_argument("--listening-links", type=Path, default=DEFAULT_LINKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{label} not found: {path}")


def episode_number(title: str) -> int | None:
    match = EPISODE_NUMBER_RE.match(title.strip())
    return int(match.group(1)) if match else None


def load_listen_urls(path: Path) -> tuple[dict[str, str], str | None]:
    if not path.is_file():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    show_url = payload.get("showUrl")
    by_episode_id: dict[str, str] = {}
    for url in payload.get("links", {}).values():
        episode_id = parse_qs(urlparse(url).query).get("i", [None])[0]
        if episode_id:
            by_episode_id[str(episode_id)] = url
    return by_episode_id, show_url


def iso_date(value: str) -> str:
    return value[:10]


def quarter(value: str) -> str:
    month = int(value[5:7])
    return f"{value[:4]}-Q{((month - 1) // 3) + 1}"


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def build_index(args: argparse.Namespace) -> dict[str, object]:
    require_file(args.turns, "Turn corpus")
    require_file(args.episodes, "Episode metadata")
    listen_urls, show_url = load_listen_urls(args.listening_links)
    episode_rows = json.loads(args.episodes.read_text(encoding="utf-8"))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    building = args.output.with_suffix(args.output.suffix + ".building")
    if building.exists():
        building.unlink()

    connection = sqlite3.connect(building)
    connection.executescript(SCHEMA)
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA temp_store = MEMORY")

    known_episodes: dict[str, dict[str, object]] = {}
    for item in episode_rows:
        episode_id = str(item["episode_id"])
        known_episodes[episode_id] = item
        connection.execute(
            """
            INSERT INTO episodes(
              episode_id, episode_number, title, published_at, published_date,
              source_file, turn_count, word_count, listen_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                episode_number(item["title"]),
                item["title"],
                item["published_at"],
                iso_date(item["published_at"]),
                item.get("source_file"),
                int(item.get("turn_count", 0)),
                int(item.get("word_count", 0)),
                listen_urls.get(episode_id, show_url),
            ),
        )

    insert_turn = """
      INSERT INTO turns(
        episode_id, episode_title, published_at, published_date, year, quarter,
        turn_index, timestamp, start_seconds, speaker, canonical_host,
        attribution_status, text, word_count, listen_url
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    digest = hashlib.sha256()
    batch: list[tuple[object, ...]] = []
    indexed_turns = 0
    indexed_words = 0

    with args.turns.open("rb") as source:
        for raw_line in source:
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            item = json.loads(raw_line)
            episode_id = str(item["episode_id"])
            if episode_id not in known_episodes:
                raise ValueError(f"Turn references unknown episode {episode_id}")
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            published_at = str(item["published_at"])
            words = word_count(text)
            batch.append(
                (
                    episode_id,
                    item["episode_title"],
                    published_at,
                    iso_date(published_at),
                    int(published_at[:4]),
                    quarter(published_at),
                    int(item["turn_index"]),
                    str(item.get("timestamp") or "0:00"),
                    float(item.get("start_seconds") or 0),
                    str(item.get("speaker") or item.get("speaker_raw") or "Unknown"),
                    item.get("canonical_host"),
                    item.get("attribution_status"),
                    text,
                    words,
                    listen_urls.get(episode_id, show_url),
                )
            )
            indexed_turns += 1
            indexed_words += words
            if len(batch) >= 1000:
                connection.executemany(insert_turn, batch)
                batch.clear()
        if batch:
            connection.executemany(insert_turn, batch)

    connection.execute(
        "INSERT INTO turns_fts(rowid, episode_title, speaker, text) "
        "SELECT id, episode_title, speaker, text FROM turns"
    )
    connection.execute("INSERT INTO turns_fts(turns_fts) VALUES('optimize')")

    date_range = connection.execute(
        "SELECT MIN(published_date), MAX(published_date) FROM episodes"
    ).fetchone()
    metadata = {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": digest.hexdigest(),
        "episode_count": str(len(episode_rows)),
        "turn_count": str(indexed_turns),
        "word_count": str(indexed_words),
        "start_date": date_range[0],
        "end_date": date_range[1],
        "source_name": "Spoken Archive normalized All-In transcripts",
    }
    connection.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items()
    )
    connection.commit()

    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    fts_count = connection.execute("SELECT COUNT(*) FROM turns_fts").fetchone()[0]
    episode_count = connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    connection.close()
    if integrity != "ok" or fts_count != indexed_turns or episode_count != len(episode_rows):
        building.unlink(missing_ok=True)
        raise RuntimeError(
            f"Index validation failed: integrity={integrity}, "
            f"fts={fts_count}/{indexed_turns}, episodes={episode_count}/{len(episode_rows)}"
        )

    os.replace(building, args.output)
    return {
        "output": str(args.output),
        "bytes": args.output.stat().st_size,
        "episodes": len(episode_rows),
        "turns": indexed_turns,
        "words": indexed_words,
        "start_date": date_range[0],
        "end_date": date_range[1],
        "source_sha256": digest.hexdigest(),
    }


def main() -> None:
    args = parse_args()
    result = build_index(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
