#!/usr/bin/env python3
"""Run lightweight structural checks for the Cursor plugin package."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".cursor-plugin/plugin.json"
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    try:
        block = text.split("---\n", 2)[1]
    except IndexError as exc:
        raise ValueError("unterminated YAML frontmatter") from exc
    values: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def main() -> None:
    errors: list[str] = []
    if not MANIFEST_PATH.is_file():
        errors.append("missing .cursor-plugin/plugin.json")
    else:
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"plugin.json is invalid JSON: {exc}")
            manifest = {}
        name = manifest.get("name", "")
        if not NAME_RE.fullmatch(name):
            errors.append("plugin name is not valid lowercase kebab-case")
        version = manifest.get("version", "")
        if version and not SEMVER_RE.fullmatch(version):
            errors.append("plugin version is not semantic version format")
        for key in ("description", "author", "license"):
            if not manifest.get(key):
                errors.append(f"manifest is missing recommended field: {key}")
        for key in ("skills", "agents", "commands", "mcpServers"):
            value = manifest.get(key)
            if isinstance(value, str):
                path = (ROOT / value).resolve()
                if ROOT not in path.parents and path != ROOT:
                    errors.append(f"{key} path escapes plugin root: {value}")
                elif not path.exists():
                    errors.append(f"{key} path does not exist: {value}")

    try:
        mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
        server = mcp["mcpServers"]["all-in-bot"]
        if server.get("url") != "https://all-in-grok-production.up.railway.app/mcp":
            errors.append("all-in-bot MCP server must use the production Railway endpoint")
        if server.get("headers"):
            errors.append("public all-in-bot MCP server must not require install-time headers")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"invalid mcp.json: {exc}")

    if manifest.get("variables"):
        errors.append("public all-in-bot plugin must not require install-time variables")

    component_paths = [
        *ROOT.glob("skills/*/SKILL.md"),
        *ROOT.glob("agents/*.md"),
        *ROOT.glob("commands/*.md"),
    ]
    if not component_paths:
        errors.append("no plugin components found")
    for path in component_paths:
        try:
            values = frontmatter(path)
        except ValueError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        for key in ("name", "description"):
            if not values.get(key):
                errors.append(f"{path.relative_to(ROOT)}: missing {key} frontmatter")

    if not (ROOT / "assets/logo.svg").is_file():
        errors.append("manifest logo is missing")
    if not (ROOT / "README.md").is_file():
        errors.append("README.md is missing")

    if errors:
        print("Plugin validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    index_status = "present" if (ROOT / "data/all-in-grok.sqlite3").is_file() else "not built"
    print("Plugin validation passed")
    print(f"- manifest: {MANIFEST_PATH}")
    print(f"- components: {len(component_paths)}")
    print(f"- private index: {index_status}")


if __name__ == "__main__":
    main()
