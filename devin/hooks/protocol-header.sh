#!/usr/bin/env bash
# Keep the small, authoritative protocol header current and inject it safely.
set -euo pipefail
INPUT_JSON="$(cat 2>/dev/null || true)"
export INPUT_JSON
python3 - "$@" <<'PY'
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

START = "<!-- PROTOCOL-HEADER:START -->"
END = "<!-- PROTOCOL-HEADER:END -->"
MAX_BYTES = 8192
MAX_STATUS = 900


def project_name(text, path):
    match = re.search(r"^#\s+(.+?)(?:\s+—\s+|\s+-\s+)([^\n]+)$", text, re.MULTILINE)
    return match.group(2).strip() if match else path.parent.name


def first_value(text, labels, paragraph=False):
    pattern = r"^\*\*(?:" + "|".join(labels) + r"):?[ \t]*(.*)$"
    match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if not match:
        return ""
    value = match.group(1)
    if paragraph:
        tail = text[match.end():]
        continuation = re.split(r"\n\s*\n|\n\*\*[^\n]+", tail, maxsplit=1)[0]
        value += " " + continuation
    return re.sub(r"\s+", " ", value).replace("**", "").strip()


def phase_from(status, text):
    match = re.search(r"\b(?:Phase|Fase)\s+(\d+)(?:\s+[^\n]*)?", status, re.IGNORECASE)
    if match:
        return match.group(1)
    phases = re.findall(r"^###\s+Phase\s+(\d+)", text, re.MULTILINE | re.IGNORECASE)
    return phases[-1] if phases else "not stated"


def body_without_header(text):
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\s*\n?", re.DOTALL)
    return pattern.sub("", text, count=1)


def section_index(text):
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines, 1):
        if re.match(r"^##\s+", line) and not line.startswith("## reviewer-architect"):
            title = re.sub(r"^##\s+", "", line).strip()
            result.append(f"{title} (line {i})")
    return result[:8]


def phase_index(text):
    result = []
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^###\s+(?:Phase|Fase)\s+", line, re.IGNORECASE):
            result.append(f"{re.sub(r'^###\\s+', '', line).strip()} (line {i})")
    if len(result) <= 12:
        return result
    return result[:4] + [f"... {len(result) - 12} earlier/later phase headings omitted; search the full body ..."] + result[-7:]


def build_header(path, text):
    status = first_value(text, ["Status", "Estado"], paragraph=True) or "NOT STATED — update the body before relying on phase state"
    status = status[:MAX_STATUS]
    updated = first_value(text, ["Updated", "Last updated", "Última atualização", "Ultima atualização"])
    if not updated:
        updated = "not stated in protocol body"
    phase = phase_from(status, text)
    pidx = phase_index(text)
    sidx = section_index(text)
    lines = [
        START,
        "# PROTOCOL HEADER — READ FIRST",
        "This is the authoritative current-state summary. The full protocol body is the source of history and evidence.",
        f"**Project:** {project_name(text, path)}",
        f"**Current phase:** {phase}",
        f"**Last updated (body):** {updated}",
        f"**Current status (body):** {status}",
        "",
        "## How to use this protocol",
        "1. Treat every claim as H0 (failure mode) vs H1 (expected result).",
        "2. Require a measurable acceptance criterion and record each case pass/fail.",
        "3. Work in order: Discovery → Pilot (3–5 real cases) → approval → Scale → Monitor.",
        "4. Never scale on a partial pilot; document failures and the evidence that resolved them.",
        "5. Read the full body before acting; this header intentionally does not replace history.",
        "",
        "## Phase index (details are in the full body)",
    ]
    lines.extend(f"- {item}" for item in (pidx or ["No Phase headings found — define the current phase in the body."]))
    lines.append(f"- Current phase details: search the full body for `Phase {phase}`; line numbers above are body offsets.")
    lines += [
        "",
        "## Non-negotiable gates",
        "- Phase 1 is read-only discovery; Phase 2 must test 3–5 real cases.",
        "- Phase 2 must be 100% pass and explicitly approved before Phase 3.",
        "- Phase 3 results must be measured from the real system; Phase 4 monitors outcomes.",
        "- Do not claim production confirmation without running the confirming query.",
        "",
        "## Body index",
    ]
    lines.extend(f"- {item}" for item in (sidx or ["No level-2 sections found."]))
    lines += [
        "",
        "**Next action:** read the body, verify the current phase/status, then state the session start before acting.",
        END,
    ]
    header = "\n".join(lines) + "\n"
    if len(header.encode()) > MAX_BYTES:
        raise ValueError(f"generated header exceeds {MAX_BYTES} bytes")
    return header


def check(path):
    text = path.read_text(encoding="utf-8")
    errors = []
    if text.count(START) != 1 or text.count(END) != 1:
        errors.append("expected exactly one START and END marker")
    elif text.index(START) > text.index(END):
        errors.append("START marker must precede END marker")
    if text[: text.find(END) + len(END)].count("\n") > 80:
        errors.append("header must end within first 80 lines")
    header = text[text.find(START): text.find(END) + len(END)] if START in text and END in text else ""
    if len(header.encode()) > MAX_BYTES:
        errors.append(f"header exceeds {MAX_BYTES} bytes")
    for label in ("Project", "Current phase", "Last updated", "Current status", "Phase index", "Body index"):
        if not re.search(rf"\*\*{re.escape(label)}[^\n]*|## {re.escape(label)}", header):
            errors.append(f"missing readable {label}")
    if errors:
        for error in errors:
            print(f"FAIL: {path}: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {path}: header valid ({len(header.encode())} bytes)")
    return 0


def sync(path):
    text = path.read_text(encoding="utf-8")
    body = body_without_header(text)
    header = build_header(path, body)
    if text.startswith(START):
        new_text = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\s*\n?", header, text, count=1, flags=re.DOTALL)
    else:
        new_text = header + text
    if new_text != text:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
        print(f"UPDATED: {path}")
    else:
        print(f"UNCHANGED: {path}")
    return check(path)


def protocol_for(data):
    cwd = Path(data.get("cwd") or os.getcwd())
    tool_input = data.get("tool_input") or {}
    candidate = tool_input.get("file_path") or tool_input.get("path")
    if candidate:
        p = Path(candidate)
        if not p.is_absolute():
            p = cwd / p
        if p.name == "SCIENTIFIC_PROTOCOL.md":
            return p
    return cwd / "SCIENTIFIC_PROTOCOL.md"


def hook():
    data = json.loads(os.environ.get("INPUT_JSON") or "{}")
    event = data.get("hook_event_name") or data.get("hookEventName") or ""
    path = protocol_for(data)
    context = []
    if path.is_file():
        # UserPromptSubmit also repairs edits performed through opaque shell commands.
        with contextlib.redirect_stdout(io.StringIO()):
            sync(path)
            valid = check(path) == 0
        context.append(path.read_text(encoding="utf-8")[:MAX_BYTES])
        context.append(f"Header validation: {'PASS' if valid else 'FAIL'} — full protocol: {path}")
    output = {"hookSpecificOutput": {"hookEventName": event or "UserPromptSubmit", "additionalContext": "\n".join(context)}}
    print(json.dumps(output, ensure_ascii=False))
    return 0


command = sys.argv[1] if len(sys.argv) > 1 else "check"
path = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else None
if command in {"sync", "check", "emit"}:
    if not path or not path.is_file():
        print("usage: protocol-header.sh sync|check|emit FILE", file=sys.stderr)
        sys.exit(2)
    if command == "sync":
        sys.exit(sync(path))
    if command == "check":
        sys.exit(check(path))
    print(path.read_text(encoding="utf-8").split(END, 1)[0] + END)
    sys.exit(0)
elif command == "hook":
    sys.exit(hook())
else:
    print("usage: protocol-header.sh sync|check|emit FILE", file=sys.stderr)
    sys.exit(2)
PY
