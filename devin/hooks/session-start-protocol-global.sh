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
  "$DEVIN_DOCS_DIR/ENFORCEMENT_CHECKLIST.md"
  "$DEVIN_DOCS_DIR/README_SESSIONS.md"
)

CONTEXT="MANDATORY READING injected automatically by the global SessionStart hook (session-start-protocol-global.sh) — does not depend on the agent choosing to read it."

for f in "${GLOBAL_FILES[@]}"; do
  if [ -f "$f" ]; then
    CONTEXT="$CONTEXT

=== $f ===
$(cat "$f")"
  fi
done

# Walk up from the session's directory: a session very often starts in a
# subdirectory of the repo (monorepo package, server/, web/), while the
# protocol lives at the root. Checking only "$CWD" missed it there, and missed
# it silently — the session then ran with no phase, status or open hypotheses.
# Deepest match wins, so a nested protocol still overrides its parent's.
find_project_protocol() {
  _d="$1"
  while [ -n "$_d" ] && [ "$_d" != "/" ]; do
    if [ -f "$_d/SCIENTIFIC_PROTOCOL.md" ]; then
      printf '%s\n' "$_d/SCIENTIFIC_PROTOCOL.md"
      return 0
    fi
    _d="$(dirname "$_d")"
  done
  [ -f "/SCIENTIFIC_PROTOCOL.md" ] && printf '%s\n' "/SCIENTIFIC_PROTOCOL.md" && return 0
  return 1
}
PROJECT_PROTOCOL="$(find_project_protocol "$CWD" || true)"
HEADER_SCRIPT="${DEVIN_HOOKS_DIR:-$HOME/.devin/hooks}/protocol-header.sh"
if [ -f "$PROJECT_PROTOCOL" ]; then
  if [ -x "$HEADER_SCRIPT" ]; then
    "$HEADER_SCRIPT" sync "$PROJECT_PROTOCOL" </dev/null >/dev/null 2>&1 || true
    PROTOCOL_HEADER=$("$HEADER_SCRIPT" emit "$PROJECT_PROTOCOL" </dev/null 2>/dev/null || true)
  fi
  if [ -n "${PROTOCOL_HEADER:-}" ]; then
    CONTEXT="$CONTEXT

=== CURRENT PROTOCOL HEADER (authoritative; full history at $PROJECT_PROTOCOL) ===
$PROTOCOL_HEADER"
  else
    CONTEXT="$CONTEXT

=== CURRENT PROTOCOL ===
Header unavailable; read the full file with the read tool: $PROJECT_PROTOCOL"
  fi
fi

# Use stdin instead of --arg to avoid ARG_MAX overflow on large protocols
# (e.g. a project SCIENTIFIC_PROTOCOL.md can be >700KB, exceeding the OS
# argument limit when passed via jq --arg "$CONTEXT").
printf '%s' "$CONTEXT" | jq -R -n --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
