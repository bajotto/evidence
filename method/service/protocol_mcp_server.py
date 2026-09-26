#!/usr/bin/env python3
"""Service-mode delivery for the scientific method: one persistent MCP server.

Standalone mode (the rest of this repo) delivers the protocol by having each
tool's own hook re-run protocol-header.sh/protocol-search.sh per session, per
prompt. That works with zero daemon and zero shared state, but it means every
MCP-capable client needs its own bespoke hook adapter written and tested
against that specific tool.

Service mode is the other half of the trade-off: a single long-lived process,
speaking plain MCP over stdio (JSON-RPC 2.0, newline-delimited — no headers,
confirmed against the MCP 2024-11-05 specification), that any MCP client can
point at. Cursor, Codex CLI, and Trae IDE all support MCP as of this writing
(see method/MULTI_AGENT_MULTI_MACHINE.md for how that was verified rather
than assumed) — wiring one client config per tool is a few lines, versus a
full hook adapter each.

This process does not replace the standalone hooks; it is registered
alongside them. It intentionally does not re-implement protocol-header.sh's
or protocol-search.sh's parsing logic — it shells out to the same scripts
every other adapter uses, so there is exactly one place that logic lives.

No third-party dependency: this hand-rolls the small slice of JSON-RPC 2.0
that MCP tools require (initialize, tools/list, tools/call), matching the
zero-dependency, stdlib-only convention of every other script in this repo.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
METHOD_DIR = HERE.parent
PROTOCOL_HEADER_SH = METHOD_DIR / "protocol-header.sh"
PROTOCOL_SEARCH_SH = METHOD_DIR / "protocol-search.sh"
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scientific-method-protocol"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "protocol_header",
        "description": (
            "Return the current PROTOCOL-HEADER (phase, status, phase/body "
            "index, gates) for the SCIENTIFIC_PROTOCOL.md nearest to "
            "project_path, re-syncing it first. Use this instead of reading "
            "the whole protocol file just to check current phase/status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Any path inside the project; the nearest ancestor SCIENTIFIC_PROTOCOL.md is used.",
                }
            },
            "required": ["project_path"],
        },
    },
    {
        "name": "protocol_search",
        "description": (
            "Query the SCIENTIFIC_PROTOCOL.md nearest to project_path without "
            "reading the whole body: list hypotheses with status, list "
            "incidents (optionally filtered), print one phase section, or "
            "free-text grep with enclosing-section context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": "Any path inside the project; the nearest ancestor SCIENTIFIC_PROTOCOL.md is used.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["hypotheses", "incidents", "phase", "grep"],
                },
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern — required for 'grep', optional filter for 'incidents'.",
                },
                "phase_number": {
                    "type": "string",
                    "description": "Required for mode 'phase' — e.g. '2'.",
                },
            },
            "required": ["project_path", "mode"],
        },
    },
]


def find_protocol(start: str) -> Path | None:
    """Walk upward from `start` looking for SCIENTIFIC_PROTOCOL.md.

    Mirrors claude/hooks/session-start-protocol-global.sh's find_project_protocol:
    the nearest (deepest) match wins, so a nested protocol overrides an
    ancestor's, and search stops at filesystem root without inventing a match
    outside any project.
    """
    d = Path(start).resolve()
    if d.is_file():
        d = d.parent
    while True:
        candidate = d / "SCIENTIFIC_PROTOCOL.md"
        if candidate.is_file():
            return candidate
        if d.parent == d:
            return None
        d = d.parent


def text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_protocol_header(args: dict) -> dict:
    project_path = args.get("project_path", "")
    protocol = find_protocol(project_path)
    if protocol is None:
        return text_result(f"No SCIENTIFIC_PROTOCOL.md found at or above {project_path!r}", is_error=True)
    subprocess.run([str(PROTOCOL_HEADER_SH), "sync", str(protocol)], capture_output=True, timeout=15)
    proc = subprocess.run(
        [str(PROTOCOL_HEADER_SH), "emit", str(protocol)],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        return text_result(proc.stderr or "protocol-header.sh emit failed", is_error=True)
    return text_result(proc.stdout)


def call_protocol_search(args: dict) -> dict:
    project_path = args.get("project_path", "")
    mode = args.get("mode", "")
    if mode not in {"hypotheses", "incidents", "phase", "grep"}:
        return text_result(f"Unknown mode {mode!r}; expected hypotheses|incidents|phase|grep", is_error=True)
    protocol = find_protocol(project_path)
    if protocol is None:
        return text_result(f"No SCIENTIFIC_PROTOCOL.md found at or above {project_path!r}", is_error=True)
    cmd = [str(PROTOCOL_SEARCH_SH), mode, str(protocol)]
    if mode == "grep":
        pattern = args.get("pattern")
        if not pattern:
            return text_result("mode 'grep' requires 'pattern'", is_error=True)
        cmd.append(pattern)
    elif mode == "phase":
        number = args.get("phase_number")
        if not number:
            return text_result("mode 'phase' requires 'phase_number'", is_error=True)
        cmd.append(number)
    elif mode == "incidents" and args.get("pattern"):
        cmd.append(args["pattern"])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    output = proc.stdout or proc.stderr
    return text_result(output, is_error=proc.returncode != 0)


DISPATCH = {
    "protocol_header": call_protocol_header,
    "protocol_search": call_protocol_search,
}


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {}) or {}
        handler = DISPATCH.get(name)
        if handler is None:
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            result = handler(arguments)
        except Exception as exc:  # noqa: BLE001 - report to the client, don't crash the server
            result = text_result(f"{type(exc).__name__}: {exc}", is_error=True)
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}}), flush=True)
            continue
        try:
            response = handle_request(msg)
        except Exception as exc:  # noqa: BLE001 - never let a single bad message kill the server
            response = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": f"Internal error: {exc}"}}
        if response is not None:
            print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
