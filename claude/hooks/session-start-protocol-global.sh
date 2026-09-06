#!/usr/bin/env bash
# Global SessionStart hook for Claude Code.
#
# Injects the mandatory "read first" docs into context automatically for
# EVERY project on this machine, instead of relying on each project's
# CLAUDE.md linking out to them. A link depends on the agent choosing to
# open it; this does not — it fires before any action, every session.
#
# It always injects the docs listed in GLOBAL_FILES below, and additionally
# injects <project>/SCIENTIFIC_PROTOCOL.md if the current project (detected
# from cwd) has one — no per-project hook setup needed.
#
# This does NOT guarantee the injected rules are followed, only that they
# are delivered. See ../../method/ENFORCEMENT_MODEL.md for why that
# distinction matters and what closes the remaining gap.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$STDIN_JSON" | jq -r '.cwd // empty' 2>/dev/null || true)"
if [ -z "$CWD" ]; then CWD="$(pwd)"; fi

CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"

# Edit this list to point at your own global rule files.
GLOBAL_FILES=(
  "$CLAUDE_DIR/SCIENTIFIC_METHOD.md"
  "$CLAUDE_DIR/ENFORCEMENT_MODEL.md"
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
  CONTEXT="$CONTEXT

=== $PROJECT_PROTOCOL ===
$(cat "$PROJECT_PROTOCOL")"
fi

# Use stdin instead of --arg to avoid ARG_MAX overflow on large protocols
# (e.g. a project SCIENTIFIC_PROTOCOL.md can be >700KB, exceeding the OS
# argument limit when passed via jq --arg "$CONTEXT").
printf '%s' "$CONTEXT" | jq -R -n --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
