#!/usr/bin/env python3
"""Create the compressed, private SQLite artifact used by the HTTP MCP function."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data/all-in-grok.sqlite3"
DEFAULT_OUTPUT = ROOT / "data/all-in-grok.sqlite3.gz"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"Index not found: {args.source}. Run scripts/build_index.py first.")

    connection = sqlite3.connect(f"file:{args.source.resolve().as_posix()}?mode=ro", uri=True)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    connection.close()
    if integrity != "ok":
        raise SystemExit(f"Refusing to package invalid index: {integrity}")

    temporary = args.output.with_suffix(args.output.suffix + ".building")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.source.open("rb") as source, gzip.open(temporary, "wb", compresslevel=9) as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    os.replace(temporary, args.output)
    print(json.dumps({
        "output": str(args.output),
        "compressed_bytes": args.output.stat().st_size,
        "source_bytes": args.source.stat().st_size,
        "episodes": int(metadata["episode_count"]),
        "turns": int(metadata["turn_count"]),
        "source_sha256": metadata["source_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
