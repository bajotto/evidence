#!/usr/bin/env bash
# Global SessionStart hook for Devin CLI (~/.devin/hooks.v1.json).
#
# Same mechanism and the same output format as the Claude Code hook in
# ../../claude/hooks/ — empirically confirmed compatible: pointing Devin's
# SessionStart hook at a script using this exact output shape correctly
# delivers content into a real Devin session (verified with `devin -p`,
# not assumed from documentation).
#
# Injects the global method docs into every session, on every project on
# this machine. Also injects <project>/SCIENTIFIC_PROTOCOL.md if the
# current project (detected from cwd) has one.
#
# This guarantees DELIVERY, not compliance — see ../../method/ENFORCEMENT_MODEL.md.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$STDIN_JSON" | jq -r '.cwd // empty' 2>/dev/null || true)"
if [ -z "$CWD" ]; then CWD="$(pwd)"; fi

DEVIN_DOCS_DIR="${DEVIN_DOCS_DIR:-$HOME/.devin/scientific-method}"

GLOBAL_FILES=(
  "$DEVIN_DOCS_DIR/SCIENTIFIC_METHOD.md"
  "$DEVIN_DOCS_DIR/ENFORCEMENT_MODEL.md"
)

CONTEXT="MANDATORY READING injected automatically by the global SessionStart hook (session-start-protocol-global.sh) — does not depend on the agent choosing to read it."

for f in "${GLOBAL_FILES[@]}"; do
  if [ -f "$f" ]; then
    CONTEXT="$CONTEXT

=== $f ===
$(cat "$f")"
  fi
done

PROJECT_PROTOCOL="$CWD/SCIENTIFIC_PROTOCOL.md"
if [ -f "$PROJECT_PROTOCOL" ]; then
  PROTO_SIZE=$(wc -c < "$PROJECT_PROTOCOL")
  PROTO_CAP=51200  # 50KB — larger protocols bloat context/token cost
  if [ "$PROTO_SIZE" -gt "$PROTO_CAP" ]; then
    CONTEXT="$CONTEXT

=== $PROJECT_PROTOCOL ===
[TRUNCATED — file is ${PROTO_SIZE} bytes, capped at ${PROTO_CAP}. Read the full file with the read tool.]
$(head -c "$PROTO_CAP" "$PROJECT_PROTOCOL")
[... TRUNCATED — read $PROJECT_PROTOCOL for the full content]"
  else
    CONTEXT="$CONTEXT

=== $PROJECT_PROTOCOL ===
$(cat "$PROJECT_PROTOCOL")"
  fi
fi

# Use stdin instead of --arg to avoid ARG_MAX overflow on large protocols
# (e.g. a project SCIENTIFIC_PROTOCOL.md can be >700KB, exceeding the OS
# argument limit when passed via jq --arg "$CONTEXT").
printf '%s' "$CONTEXT" | jq -R -n --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
