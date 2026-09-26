#!/usr/bin/env bash
# Global SessionStart hook for Claude Code.
#
# Injects the mandatory "read first" docs into context automatically for
# EVERY project on this machine, instead of relying on each project's
# CLAUDE.md linking out to them. A link depends on the agent choosing to
# open it; this does not — it fires before any action, every session.
#
# Injects:
#   - Upstream canonical method (EVIDENCE.md, ENFORCEMENT_MODEL.md)
#   - Local operational docs (ENFORCEMENT_CHECKLIST.md, README_SESSIONS.md)
#   - <project>/EVIDENCE_PROTOCOL.md if the current project has one
#   - <project>/.claude/session-state.sh if it exists (live DB state)
#
# This does NOT guarantee the injected rules are followed, only that they
# are delivered. See ENFORCEMENT_MODEL.md for why that distinction matters
# and what closes the remaining gap.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$STDIN_JSON" | jq -r '.cwd // empty' 2>/dev/null || true)"
if [ -z "$CWD" ]; then CWD="$(pwd)"; fi

CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"

# Upstream canonical method (conceitual: H0/H1, fases, 3 camadas)
# + local operational docs (checklist de regras, instruções de sessão)
GLOBAL_FILES=(
  "$CLAUDE_DIR/EVIDENCE.md"
  "$CLAUDE_DIR/ENFORCEMENT_MODEL.md"
  "$CLAUDE_DIR/ENFORCEMENT_CHECKLIST.md"
  "$CLAUDE_DIR/README_SESSIONS.md"
)

CONTEXT="LEITURA OBRIGATORIA injetada automaticamente por hook SessionStart global (~/.claude/hooks/session-start-protocol-global.sh) — nao depende de o agente escolher ler."

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
    if [ -f "$_d/EVIDENCE_PROTOCOL.md" ]; then
      printf '%s\n' "$_d/EVIDENCE_PROTOCOL.md"
      return 0
    fi
    _d="$(dirname "$_d")"
  done
  [ -f "/EVIDENCE_PROTOCOL.md" ] && printf '%s\n' "/EVIDENCE_PROTOCOL.md" && return 0
  return 1
}
PROJECT_PROTOCOL="$(find_project_protocol "$CWD" || true)"
HEADER_SCRIPT="$CLAUDE_DIR/hooks/protocol-header.sh"
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

# Optional: project-level live state script. If <cwd>/.claude/session-state.sh
# exists and is executable, run it and inject its stdout as "ESTADO ATUAL".
# This solves protocol staleness: the agent sees real DB state at session start
# instead of relying on hand-edited markdown. Script must be read-only (SELECT)
# and fail graceful (output a notice, not crash) if its data source is down.
# Projects without this script are unaffected.
#
# TRUST ASSUMPTION: this script executes with the user's privileges at every
# session start. Only trusted project owners should place a session-state.sh.
# There is no sandbox — the script can do anything the user can. This is
# acceptable on a single-user dev machine; on shared infrastructure, remove
# this block or wrap in a restricted shell.
PROJECT_STATE="$CWD/.claude/session-state.sh"
if [ -x "$PROJECT_STATE" ]; then
  STATE_ERR_FILE=$(mktemp)
  STATE_OUT="$("$PROJECT_STATE" 2>"$STATE_ERR_FILE")"
  STATE_ERR="$(cat "$STATE_ERR_FILE" 2>/dev/null || true)"
  rm -f "$STATE_ERR_FILE"
  if [ -n "$STATE_OUT" ]; then
    CONTEXT="$CONTEXT

=== ESTADO ATUAL (ao vivo, via $PROJECT_STATE) ===
$STATE_OUT"
  elif [ -n "$STATE_ERR" ]; then
    CONTEXT="$CONTEXT

=== ESTADO ATUAL (ao vivo) — FALHOU ===
$PROJECT_STATE retornou erro:
$STATE_ERR"
  fi
fi

# Use stdin instead of --arg to avoid ARG_MAX overflow on large protocols
# (e.g. jobs-agent EVIDENCE_PROTOCOL.md is ~722KB)
printf '%s' "$CONTEXT" | jq -R -n --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
