#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for client in claude devin; do
  PROJECT="$TMP/$client-project"
  mkdir -p "$PROJECT/.evidence"
  printf '%s\n' '{"service_url":"https://evidence.example/mcp","project_slug":"central-test","protocol_source":"central"}' > "$PROJECT/.evidence/project.json"
  printf '%s\n' 'STALE_LOCAL_PROTOCOL_MARKER' > "$PROJECT/EVIDENCE_PROTOCOL.md"

  if [ "$client" = claude ]; then
    HOME_DIR="$TMP/home-claude"
    mkdir -p "$HOME_DIR/.claude/hooks"
    cp "$ROOT/method/protocol-header.sh" "$HOME_DIR/.claude/hooks/protocol-header.sh"
    chmod +x "$HOME_DIR/.claude/hooks/protocol-header.sh"
    OUT="$(printf '{"cwd":"%s"}' "$PROJECT" | HOME="$HOME_DIR" CLAUDE_DIR="$HOME_DIR/.claude" bash "$ROOT/claude/hooks/session-start-protocol-global.sh")"
  else
    HOME_DIR="$TMP/home-devin"
    mkdir -p "$HOME_DIR/.devin/hooks"
    cp "$ROOT/method/protocol-header.sh" "$HOME_DIR/.devin/hooks/protocol-header.sh"
    chmod +x "$HOME_DIR/.devin/hooks/protocol-header.sh"
    OUT="$(printf '{"cwd":"%s"}' "$PROJECT" | HOME="$HOME_DIR" DEVIN_HOOKS_DIR="$HOME_DIR/.devin/hooks" DEVIN_DOCS_DIR="$HOME_DIR/.devin/evidence" bash "$ROOT/devin/hooks/session-start-protocol-global.sh")"
  fi

  printf '%s' "$OUT" | jq -e '.hookSpecificOutput.additionalContext | contains("CENTRAL EVIDENCE MODE") and contains("central-test") and (contains("STALE_LOCAL_PROTOCOL_MARKER") | not)' >/dev/null
  printf 'PASS: %s global hook prefers central manifest over local protocol snapshot\n' "$client"
done
