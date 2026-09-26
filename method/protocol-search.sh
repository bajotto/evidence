#!/usr/bin/env bash
# Search a SCIENTIFIC_PROTOCOL.md body without loading all of it into context.
#
# The PROTOCOL-HEADER stays capped at 8KB (see protocol-header.sh), but the
# body it summarizes does not: one real project's protocol reached ~722KB.
# Injecting that whole body every session/prompt is neither necessary nor
# affordable. This script is the other half of that trade-off — a way to
# query the body on demand (by hypothesis, incident, phase, or free text)
# instead of reading all of it every time.
set -euo pipefail
python3 - "$@" <<'PY'
import re
import sys
from pathlib import Path

START = "<!-- PROTOCOL-HEADER:START -->"
END = "<!-- PROTOCOL-HEADER:END -->"


def body_without_header(text):
    if START in text and END in text:
        return text[text.index(END) + len(END):].lstrip("\n")
    return text


def usage():
    print("usage: protocol-search.sh grep FILE PATTERN", file=sys.stderr)
    print("       protocol-search.sh hypotheses FILE", file=sys.stderr)
    print("       protocol-search.sh incidents FILE [PATTERN]", file=sys.stderr)
    print("       protocol-search.sh phase FILE N", file=sys.stderr)
    sys.exit(2)


def enclosing_section(lines, idx):
    for i in range(idx, -1, -1):
        if re.match(r"^#{2,3}\s+", lines[i]):
            return lines[i].strip()
    return "(no enclosing section)"


def cmd_grep(path, pattern):
    lines = body_without_header(path.read_text(encoding="utf-8")).splitlines()
    rx = re.compile(pattern, re.IGNORECASE)
    hits = 0
    for i, line in enumerate(lines):
        if not rx.search(line):
            continue
        hits += 1
        print(f"L{i + 1} [{enclosing_section(lines, i)}]")
        lo, hi = max(0, i - 1), min(len(lines), i + 2)
        for j in range(lo, hi):
            print(f"  {'>' if j == i else ' '} {lines[j]}")
        print()
    if hits == 0:
        print(f"No matches for /{pattern}/ in {path}", file=sys.stderr)
        sys.exit(1)
    print(f"{hits} match(es).")


def cmd_hypotheses(path):
    lines = body_without_header(path.read_text(encoding="utf-8")).splitlines()
    found = False
    for i, line in enumerate(lines):
        m = re.match(r"^###\s+(H\d+\s*[:\s].*)$", line, re.IGNORECASE)
        if not m:
            continue
        found = True
        status = ""
        for j in range(i + 1, min(i + 12, len(lines))):
            if re.match(r"^###\s+", lines[j]):
                break
            sm = re.match(r"^-?\s*\*\*Status:?\*\*\s*(.*)$", lines[j], re.IGNORECASE)
            if sm:
                status = sm.group(1).strip()
                break
        print(f"L{i + 1} {m.group(1).strip()}")
        print(f"     Status: {status or '(not stated)'}")
    if not found:
        print(f"No hypotheses (### H<n> ...) found in {path}", file=sys.stderr)
        sys.exit(1)


def cmd_incidents(path, pattern):
    lines = body_without_header(path.read_text(encoding="utf-8")).splitlines()
    rx = re.compile(pattern, re.IGNORECASE) if pattern else None
    found = False
    i = 0
    while i < len(lines):
        m = re.match(r"^###\s+Incident:?\s*(.*)$", lines[i], re.IGNORECASE)
        if not m:
            i += 1
            continue
        start = i
        j = i + 1
        while j < len(lines) and not re.match(r"^###\s+", lines[j]):
            j += 1
        block = "\n".join(lines[start:j])
        if rx is None or rx.search(block):
            found = True
            what = ""
            for line in lines[start + 1:j]:
                wm = re.match(r"^-?\s*\*\*What happened:?\*\*\s*(.*)$", line, re.IGNORECASE)
                if wm:
                    what = wm.group(1).strip()
                    break
            print(f"L{start + 1} Incident: {m.group(1).strip()}")
            if what:
                print(f"     {what}")
        i = j
    if not found:
        label = f" matching /{pattern}/" if pattern else ""
        print(f"No incidents{label} found in {path}", file=sys.stderr)
        sys.exit(1)


def cmd_phase(path, number):
    lines = body_without_header(path.read_text(encoding="utf-8")).splitlines()
    pat = re.compile(rf"^###\s+Phase\s+{re.escape(number)}\b", re.IGNORECASE)
    start = next((i for i, line in enumerate(lines) if pat.match(line)), None)
    if start is None:
        print(f"Phase {number} not found in {path}", file=sys.stderr)
        sys.exit(1)
    end = start + 1
    while end < len(lines) and not re.match(r"^#{2,3}\s+", lines[end]):
        end += 1
    print("\n".join(lines[start:end]).rstrip())


args = sys.argv[1:]
if len(args) < 2:
    usage()
command, file_arg = args[0], args[1]
path = Path(file_arg)
if not path.is_file():
    print(f"file not found: {path}", file=sys.stderr)
    sys.exit(2)

if command == "grep":
    len(args) >= 3 or usage()
    cmd_grep(path, args[2])
elif command == "hypotheses":
    cmd_hypotheses(path)
elif command == "incidents":
    cmd_incidents(path, args[2] if len(args) > 2 else None)
elif command == "phase":
    len(args) >= 3 or usage()
    cmd_phase(path, args[2])
else:
    usage()
PY
