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
# this machine. Also injects <project>/EVIDENCE_PROTOCOL.md if the
# current project (detected from cwd) has one.
#
# This guarantees DELIVERY, not compliance — see ../../method/ENFORCEMENT_MODEL.md.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$STDIN_JSON" | jq -r '.cwd // empty' 2>/dev/null || true)"
if [ -z "$CWD" ]; then CWD="$(pwd)"; fi

DEVIN_DOCS_DIR="${DEVIN_DOCS_DIR:-$HOME/.devin/evidence}"

GLOBAL_FILES=(
  "$DEVIN_DOCS_DIR/EVIDENCE.md"
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

find_project_protocol() {
  _d="$1"
  while [ -n "$_d" ] && [ "$_d" != "/" ]; do
    if [ -f "$_d/EVIDENCE_PROTOCOL.md" ]; then
      printf '%s\n' "$_d/EVIDENCE_PROTOCOL.md"
      return 0
    fi
    _d="$(dirname "$_d")"
  done
  [ -f "/EVIDENCE_PROTOCOL.md" ] && printf '%s\n' "/EVIDENCE_PROTOCOL.md" && return 0
  return 1
}

find_project_central_manifest() {
  _d="$1"
  while [ -n "$_d" ] && [ "$_d" != "/" ]; do
    if [ -f "$_d/.evidence/project.json" ]; then
      printf '%s\n' "$_d/.evidence/project.json"
      return 0
    fi
    _d="$(dirname "$_d")"
  done
  [ -f "/.evidence/project.json" ] && printf '%s\n' "/.evidence/project.json" && return 0
  return 1
}

HEADER_SCRIPT="${DEVIN_HOOKS_DIR:-$HOME/.devin/hooks}/protocol-header.sh"
CENTRAL_MANIFEST="$(find_project_central_manifest "$CWD" || true)"
if [ -n "$CENTRAL_MANIFEST" ]; then
  if [ -x "$HEADER_SCRIPT" ]; then
    PROJECT_CONTEXT="$(printf '%s' "$STDIN_JSON" | "$HEADER_SCRIPT" hook 2>/dev/null | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || true)"
  else
    PROJECT_CONTEXT="Central Evidence project detected, but the installed hook is too old to handle central mode. Rerun the Devin installer."
  fi
  case "$PROJECT_CONTEXT" in
    *"CENTRAL EVIDENCE MODE"*) ;;
    *) PROJECT_CONTEXT="Central project marker found but the central-aware protocol hook is missing or failed. Rerun the Devin installer and stop before protocol-dependent actions." ;;
  esac
  CONTEXT="$CONTEXT

=== CENTRAL PROJECT STATE ===
$PROJECT_CONTEXT"
else
  PROJECT_PROTOCOL="$(find_project_protocol "$CWD" || true)"
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
fi

# Use stdin instead of --arg to avoid ARG_MAX overflow on large protocols
# (e.g. a project EVIDENCE_PROTOCOL.md can be >700KB, exceeding the OS
# argument limit when passed via jq --arg "$CONTEXT").
printf '%s' "$CONTEXT" | jq -R -n --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
