#!/usr/bin/env python3
"""Register the scientific-method MCP server in a Cursor mcp.json file.

Cursor's schema (confirmed against current docs/community guides — this repo
could not install the real Cursor binary in its test environment, see
cursor/README.md): {"mcpServers": {"<name>": {"command", "args", "env"}}}.
This merges into whatever config already exists at the target path instead
of overwriting it, the same "preserve what's already there, idempotent"
convention used for claude/install.sh's settings.json and devin/install.sh's
hooks.v1.json.

Usage: write-cursor-mcp-config.py TARGET_MCP_JSON SERVER_SCRIPT_PATH
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER_NAME = "scientific-method"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: write-cursor-mcp-config.py TARGET_MCP_JSON SERVER_SCRIPT_PATH", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    server_script = sys.argv[2]

    config: dict = {}
    if target.is_file():
        raw = target.read_text(encoding="utf-8").strip()
        if raw:
            try:
                config = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"error: {target} exists and is not valid JSON: {exc}", file=sys.stderr)
                return 1

    servers = config.setdefault("mcpServers", {})
    entry = {"command": "python3", "args": [server_script]}
    if servers.get(SERVER_NAME) == entry:
        print(f"UNCHANGED: {target} ({SERVER_NAME} already registered)")
        return 0

    servers[SERVER_NAME] = entry
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"UPDATED: {target} (registered '{SERVER_NAME}')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
