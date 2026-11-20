#!/usr/bin/env bash
# Keep the small, authoritative protocol header current and inject it safely.
set -euo pipefail
HOOK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PROTOCOL_HOOK_DIR="$HOOK_DIR"
# Only hook mode (no subcommand) is fed JSON on stdin. The CLI subcommands are
# not, and draining stdin there hangs the process whenever the caller leaves the
# pipe open — which is what a terminal, or a hook that forgot </dev/null, does.
case "${1:-}" in
  sync|check|emit) INPUT_JSON="" ;;
  *)               INPUT_JSON="$(cat 2>/dev/null || true)" ;;
esac
export INPUT_JSON
python3 - "$@" <<'PY'
import contextlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

START = "<!-- PROTOCOL-HEADER:START -->"
END = "<!-- PROTOCOL-HEADER:END -->"
MAX_BYTES = 8192
MAX_STATUS = 900
TRUNC_MARK = " …[continues in body]"


def project_name(text, path):
    # The template's own title convention is "# PROJECT_NAME — Evidence
    # Protocol" (project name first, generic suffix second) — group(1) is
    # the project name. This returned group(2) instead, so every protocol
    # following that convention reported "Evidence Protocol" itself as
    # its **Project:** value, regardless of the actual project.
    match = re.search(r"^#\s+(.+?)(?:\s+—\s+|\s+-\s+)([^\n]+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else path.parent.name


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


def status_value(text):
    status = first_value(text, ["Status", "Estado"], paragraph=True) or "NOT STATED — update the body before relying on phase state"
    if len(status) > MAX_STATUS:
        status = status[:MAX_STATUS].rsplit(" ", 1)[0].rstrip() + TRUNC_MARK
    return status


def phase_from(status, text):
    nums = re.findall(r"\b(?:Phase|Fase)\s+(\d+)", status, re.IGNORECASE)
    if nums:
        return str(max(map(int, nums)))
    phases = re.findall(r"^###\s+Phase\s+(\d+)", text, re.MULTILINE | re.IGNORECASE)
    return phases[-1] if phases else "not stated"


def body_without_header(text):
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\s*\n?", re.DOTALL)
    return pattern.sub("", text, count=1)


def header_block(text):
    start = text.find(START)
    end = text.find(END, start)
    if start >= 0 and end >= 0:
        return text[start:end + len(END)]
    return text.split(END, 1)[0] + END


def section_index(text, off=0):
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines, 1):
        if re.match(r"^##\s+", line) and not line.startswith("## reviewer-architect"):
            title = re.sub(r"^##\s+", "", line).strip()
            result.append(f"{title} (line {i + off})")
    return result[:8]


def phase_index(text, off=0):
    result = []
    for i, line in enumerate(text.splitlines(), 1):
        # "### Phase N ..." headings, or the bold "**Phase N — Name: STATUS**" lead-ins
        m = re.match(r"^(?:###\s+((?:Phase|Fase)\s+.+)|\*\*((?:Phase|Fase)\s+\d+\s+—[^*]+?)\.?\*\*)", line, re.IGNORECASE)
        if m:
            result.append(f"{(m.group(1) or m.group(2)).strip()} (line {i + off})")
    if len(result) <= 12:
        return result
    return result[:4] + [f"... {len(result) - 12} earlier/later phase headings omitted; search the full body ..."] + result[-7:]


LOG_RE = re.compile(r"^(?:#{2,4}\s+|\*\*)?(?:Incident:\s+)?(\d{4}-\d{2}-\d{2})(?:\s*\(\w+\))?\s+—\s+(.+)")


def recent_log(text, off=0, n=6):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = LOG_RE.match(line)
        if m:
            title = m.group(2).replace("**", "").strip()
            if len(title) > 90:
                title = title[:90].rsplit(" ", 1)[0] + " …"
            out.append((m.group(1), f"{m.group(1)} — {title} (line {i + off})"))
    return out[-n:]


NOW_RE = re.compile(r"<!-- PROTOCOL-NOW:START -->\s*(.*?)\s*<!-- PROTOCOL-NOW:END -->", re.DOTALL)
MAX_NOW = 1800


def now_block(text, log):
    m = NOW_RE.search(text)
    if not m:
        return ["No PROTOCOL-NOW block in the body — add one right after the header (START/END comment markers named PROTOCOL-NOW)."]
    block = m.group(1)
    if len(block.encode()) > MAX_NOW:
        block = block.encode()[:MAX_NOW].decode(errors="ignore").rsplit("\n", 1)[0] + "\n…[NOW block truncated]"
    lines = block.splitlines()
    asof = re.search(r"as of (\d{4}-\d{2}-\d{2})", block, re.IGNORECASE)
    newest = max((d for d, _ in log), default="")
    if not asof:
        lines.append("⚠ NOW block has no 'as of YYYY-MM-DD' — cannot tell if it is current.")
    elif newest and asof.group(1) < newest:
        lines.append(f"⚠ NOW block is as of {asof.group(1)} but the log has an entry from {newest} — update it.")
    return lines


def squash(items, cap, noun):
    if cap is None or len(items) <= cap:
        return items
    head, tail = items[: cap // 2], items[-(cap - cap // 2):]
    return head + [f"... {len(items) - cap} more {noun} omitted; use search (`protocol_search` or the search script) ..."] + tail


def search_section(search_script):
    if os.environ.get("EVIDENCE_CENTRAL"):  # set by the Evidence service: there is no local script or file to point at
        return [
            "This protocol lives in the Evidence service. Use the `protocol_search` MCP tool instead of reading everything:",
            "- `protocol_search` mode `hypotheses` — every H<n>, with its Status line",
            "- `protocol_search` mode `incidents` (optional pattern) — incident log, optionally filtered",
            "- `protocol_search` mode `phase` (phase_number) — just that Phase section",
            "- `protocol_search` mode `grep` (pattern) — free text, with enclosing section",
            "Use `protocol_get` only when you need the whole body; change it with `protocol_update` and `expected_revision`.",
        ]
    return [
        f"Search tool installed with this hook: `{search_script}`.",
        f"- `{search_script}` hypotheses FILE           — every H<n>, with its Status line",
        f"- `{search_script}` incidents FILE [PATTERN]  — incident log, optionally filtered",
        f"- `{search_script}` phase FILE N              — just that Phase section",
        f"- `{search_script}` grep FILE PATTERN          — free text, with enclosing section",
    ]


def build_header(path, text, off=0):
    status = status_value(text)
    updated = first_value(text, ["Updated", "Last updated", "Última atualização", "Ultima atualização"])
    if not updated:
        updated = "not stated in protocol body"
    phase = phase_from(status, text)
    pidx = phase_index(text, off)
    sidx = section_index(text, off)
    log = recent_log(text, off)
    search_script = Path(os.environ.get("PROTOCOL_HOOK_DIR", Path.home() / ".codex/hooks")) / "protocol-search.sh"
    now_lines = now_block(text, log)
    # The header must always fit its own limits (80 lines, MAX_BYTES), however many sections a protocol has: shrink the
    # indexes step by step, keeping the head and the tail and pointing at search for the rest.
    for cap in (None, 24, 16, 10, 6, 3):
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
        lines.extend(f"- {item}" for item in (squash(pidx, cap, "phase headings") or ["No Phase headings found — define the current phase in the body."]))
        lines.append(f"- Current phase details: search the file for `Phase {phase}`.")
        lines += [
            "",
            "## Now (maintained each session — trust this over the status line above)",
            *(now_lines if cap is None else now_lines[: max(cap, 4)]),
            "",
            "## Recent log (newest last, line numbers are real file lines)",
            *[f"- {x}" for _, x in (log or [("", "No dated log entries found.")])],
            "",
            "## Non-negotiable gates",
            "- Phase 1 is read-only discovery; Phase 2 must test 3–5 real cases.",
            "- Phase 2 must be 100% pass and explicitly approved before Phase 3.",
            "- Phase 3 results must be measured from the real system; Phase 4 monitors outcomes.",
            "- Do not claim production confirmation without running the confirming query.",
            "",
            "## Body index",
        ]
        lines.extend(f"- {item}" for item in (squash(sidx, cap, "sections") or ["No level-2 sections found."]))
        lines += [
            "",
            "## Full-text search (do not read the whole body just to find one thing)",
            *search_section(search_script),
            "",
            "**Next action:** read the body, verify the current phase/status, then state the session start before acting.",
            END,
        ]
        header = "\n".join(lines) + "\n"
        if header.count("\n") <= 78 and len(header.encode()) <= MAX_BYTES:
            return header
    raise ValueError("generated header exceeds the line or byte budget even with minimal indexes")


def check(path):
    text = path.read_text(encoding="utf-8")
    errors = []
    if text.count(START) != 1 or text.count(END) != 1:
        errors.append("expected exactly one START and END marker")
    elif text.index(START) > text.index(END):
        errors.append("START marker must precede END marker")
    header = text[text.find(START): text.find(END) + len(END)] if START in text and END in text else ""
    # Measured against the header block itself (START..END), not file-start..END:
    # a project's own prose before the header (the template invites exactly this —
    # "Copy this file into the root of your project...") must not count against the
    # header's own bound, and must not leak into what emit hands to an agent.
    if header.count("\n") > 80:
        errors.append("header must end within first 80 lines")
    if len(header.encode()) > MAX_BYTES:
        errors.append(f"header exceeds {MAX_BYTES} bytes")
    for label in ("Project", "Current phase", "Last updated", "Current status", "Phase index", "Body index"):
        if not re.search(rf"\*\*{re.escape(label)}[^\n]*|## {re.escape(label)}", header):
            errors.append(f"missing readable {label}")
    shown_m = re.search(r"^\*\*Current status \(body\):\*\*[ \t]*(.*)$", header, re.MULTILINE)
    if not shown_m:
        errors.append("missing readable Current status value")
    elif shown_m.group(1).strip() != status_value(body_without_header(text)):
        errors.append("header status does not match generated body status")
    if errors:
        for error in errors:
            print(f"FAIL: {path}: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {path}: header valid ({len(header.encode())} bytes)")
    return 0


def sync(path):
    text = path.read_text(encoding="utf-8")
    body = body_without_header(text)
    # body line numbers already include any prose before the header; only the header's own
    # length is missing. The line count does not depend on the numbers, so two passes suffice.
    header = build_header(path, body)
    header = build_header(path, body, header.count("\n"))
    if START in text and END in text:
        # A callable repl avoids re.sub treating backslashes/backreferences in
        # `header` specially — it is inserted verbatim either way. Matching
        # START..END anywhere (not just at position 0) matters because a real
        # protocol file, like the project template it was copied from, often
        # carries prose before the header; startswith() missed that case and
        # prepended a second header instead of replacing the existing one.
        new_text = re.sub(
            re.escape(START) + r".*?" + re.escape(END) + r"\s*\n?",
            lambda _match: header,
            text,
            count=1,
            flags=re.DOTALL,
        )
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


def find_central_manifest(start):
    directory = Path(start).resolve()
    if directory.is_file():
        directory = directory.parent
    while True:
        manifest = directory / ".evidence" / "project.json"
        if manifest.is_file():
            return manifest
        if directory.parent == directory:
            return None
        directory = directory.parent


CACHE_TTL = float(os.environ.get("EVIDENCE_HOOK_CACHE_TTL", "60"))
FETCH_TIMEOUT = float(os.environ.get("EVIDENCE_HOOK_TIMEOUT", "3"))
MAX_LIVE_HEADER = 7000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: the bearer key must only ever go to the host named in the manifest."""

    def redirect_request(self, *args, **kwargs):
        return None


def cache_file(slug):
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "evidence"
    return base / f"{slug}.json"


def load_cache(slug):
    try:
        data = json.loads(cache_file(slug).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(slug, data):
    try:
        path = cache_file(slug)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass  # a cache that cannot be written only costs one more fetch


def fetch_live(service_url, slug):
    """(status, payload). The key comes from EVIDENCE_TOKEN and is sent only to the manifest's own host."""
    token = os.environ.get("EVIDENCE_TOKEN", "")
    if not token:
        return "no-token", None
    origin = service_url.rstrip("/").removesuffix("/mcp")
    request = urllib.request.Request(f"{origin}/api/protocol/header?project={slug}",
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": "evidence-hook/1.0"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=FETCH_TIMEOUT) as response:
            data = json.load(response)
        if isinstance(data.get("header"), str) and isinstance(data.get("revision"), int):
            return "ok", data
        return "error", None
    except urllib.error.HTTPError as exc:
        return ("denied" if exc.code in (401, 403) else "error"), None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "offline", None


def central_context(manifest, event="", session_id=""):
    try:
        config = json.loads(manifest.read_text(encoding="utf-8"))
        slug = config.get("project_slug", "")
        service_url = config.get("service_url", "")
        parsed = urlparse(service_url)
        valid_slug = re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,62})[a-z0-9]", slug)
        valid_url = parsed.scheme == "https" or (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            config.get("protocol_source") != "central"
            or not valid_slug
            or not valid_url
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid central project manifest")
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        return f"CENTRAL EVIDENCE MODE CONFIGURATION FAIL — {manifest} cannot be trusted ({type(exc).__name__}). Stop before protocol-dependent actions."

    state = load_cache(slug)
    now = time.time()
    fresh = bool(state.get("header")) and now - state.get("fetched_at", 0) < CACHE_TTL and event != "SessionStart"
    status = "cache" if fresh else ""
    if not fresh:
        status, payload = fetch_live(service_url, slug)
        if status == "ok":
            state.update(header=payload["header"], revision=payload["revision"], fetched_at=now, name=payload.get("name", slug))
        elif state.get("header"):
            status = "stale-" + status
    revision, header = state.get("revision"), state.get("header", "")
    injected = state.setdefault("injected", {})
    sid = session_id or "default"
    if event == "PostToolUse" and status in ("ok", "cache") and injected.get(sid) == revision:
        return ""  # nothing new since the header was injected: stay quiet instead of repeating it after every tool call
    changed = sid in injected and injected[sid] != revision and revision is not None
    if header and status in ("ok", "cache", "stale-offline", "stale-error", "stale-denied", "stale-no-token"):
        injected[sid] = revision
        state["injected"] = dict(list(injected.items())[-20:])
        save_cache(slug, state)

    lines = [
        "CENTRAL EVIDENCE MODE — this project's authoritative protocol is in the authenticated Evidence service, not a local Markdown file.",
        f"Project slug: {slug}\nMCP service: {service_url}",
    ]
    if header:
        label = {"ok": "live from the service", "cache": "from the last fetch (under a minute old)"}.get(
            status, "STALE: the service could not be reached, this is the last copy this machine saw")
        lines.append(f"{'PROTOCOL UPDATED to revision ' + str(revision) + ' — read the new header below. ' if changed else ''}"
                     f"LIVE PROTOCOL HEADER (revision {revision}, {label}):")
        lines.append(header[:MAX_LIVE_HEADER])
    notes = {
        "no-token": "EVIDENCE_TOKEN is not set in this shell, so the live header cannot be fetched and the `evidence` MCP server cannot authenticate. "
                    "Export your Evidence secret (from the web app, Evidence secret page) and restart this session.",
        "denied": "The Evidence service rejected the key (revoked, or you are not a member of this project). Generate a new Evidence secret.",
        "offline": "The Evidence service could not be reached and nothing is cached. Do not assume the protocol state; retry the `protocol_header` MCP tool.",
        "error": "The Evidence service returned an error and nothing is cached. Retry the `protocol_header` MCP tool.",
    }
    reason = status.replace("stale-", "")
    if reason in notes and (not header or reason in ("denied", "no-token")):  # with a cached header, only actionable problems add a note
        lines.append("NOTE: " + notes[reason])
    lines.append(
        "Use the `evidence` MCP tools: `protocol_search` for a section, `protocol_get` for the full body, `protocol_update` with "
        "`expected_revision` to edit (on a conflict, reread before retrying), `protocol_sync_status` to see who has read the current revision. "
        "A local EVIDENCE_PROTOCOL.md is only an export/snapshot."
    )
    return "\n".join(lines)


def protocol_for(data):
    cwd = Path(data.get("cwd") or os.getcwd())
    tool_input = data.get("tool_input") or {}
    candidate = tool_input.get("file_path") or tool_input.get("path")
    if candidate:
        p = Path(candidate)
        if not p.is_absolute():
            p = cwd / p
        if p.name == "EVIDENCE_PROTOCOL.md":
            return p
    for d in (cwd, *cwd.parents):
        if (d / "EVIDENCE_PROTOCOL.md").is_file():
            return d / "EVIDENCE_PROTOCOL.md"
    return cwd / "EVIDENCE_PROTOCOL.md"


def hook():
    data = json.loads(os.environ.get("INPUT_JSON") or "{}")
    event = data.get("hook_event_name") or data.get("hookEventName") or ""
    central_manifest = find_central_manifest(data.get("cwd") or os.getcwd())
    context = []
    if central_manifest:
        text = central_context(central_manifest, event, str(data.get("session_id") or ""))
        if text:
            context.append(text)
            context.append(f"Central manifest: {central_manifest}")
    else:
        path = protocol_for(data)
        if path.is_file():
            with contextlib.redirect_stdout(io.StringIO()):
                sync(path)
                valid = check(path) == 0
            context.append(header_block(path.read_text(encoding="utf-8")))
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
    # emit: only the header block (START..END), never whatever precedes it.
    # A file-start..END slice used to be printed instead, which meant any
    # prose before the header (the project template itself carries some —
    # see the same startswith() bug this fixed in sync()) leaked into every
    # hook injection instead of the bounded header alone.
    emit_text = path.read_text(encoding="utf-8")
    print(header_block(emit_text))
    sys.exit(0)
elif command == "hook":
    sys.exit(hook())
else:
    print("usage: protocol-header.sh sync|check|emit FILE", file=sys.stderr)
    sys.exit(2)
PY
