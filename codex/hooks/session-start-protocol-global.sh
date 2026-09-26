#!/usr/bin/env bash
# Global Codex SessionStart hook: inject the method and current project header.
set -euo pipefail

INPUT_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$INPUT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd", ""))' 2>/dev/null || true)"
[ -n "$CWD" ] || CWD="$(pwd)"
CODEX_DIR="${CODEX_DIR:-$HOME/.codex}"
DOCS_DIR="$CODEX_DIR/scientific-method"

CONTEXT="MANDATORY READING injected automatically by Codex SessionStart hook ($CODEX_DIR/hooks/session-start-protocol-global.sh). Read before acting."
for name in SCIENTIFIC_METHOD.md ENFORCEMENT_MODEL.md; do
  file="$DOCS_DIR/$name"
  if [ -f "$file" ]; then
    CONTEXT+="\n\n=== $file ===\n$(cat "$file")"
  else
    CONTEXT+="\n\nMISSING REQUIRED METHOD DOCUMENT: $file"
  fi
done

find_protocol() {
  local dir="$1"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    if [ -f "$dir/SCIENTIFIC_PROTOCOL.md" ]; then
      printf '%s\n' "$dir/SCIENTIFIC_PROTOCOL.md"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  [ -f "/SCIENTIFIC_PROTOCOL.md" ] && { printf '%s\n' "/SCIENTIFIC_PROTOCOL.md"; return 0; }
  return 1
}

PROTOCOL="$(find_protocol "$CWD" || true)"
HEADER_SCRIPT="$CODEX_DIR/hooks/protocol-header.sh"
if [ -n "$PROTOCOL" ]; then
  if [ -x "$HEADER_SCRIPT" ]; then
    "$HEADER_SCRIPT" sync "$PROTOCOL" </dev/null >/dev/null 2>&1 || true
    HEADER="$("$HEADER_SCRIPT" emit "$PROTOCOL" </dev/null 2>/dev/null || true)"
  fi
  if [ -n "${HEADER:-}" ]; then
    CONTEXT+="\n\n=== CURRENT PROTOCOL HEADER (full history: $PROTOCOL) ===\n$HEADER"
  else
    CONTEXT+="\n\nPROTOCOL HEADER UNAVAILABLE; read full protocol: $PROTOCOL"
  fi
else
  CONTEXT+="\n\nNo SCIENTIFIC_PROTOCOL.md found from session cwd ($CWD) up to filesystem root. If this project uses the protocol, locate/read it before acting."
fi

python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.stdin.read()}},ensure_ascii=False))' <<< "$CONTEXT"
