#!/usr/bin/env bash
# OPTIONAL, best-effort Cursor sessionStart hook. NOT installed by
# install.sh — read cursor/README.md before wiring this into
# .cursor/hooks.json. As of this writing there is an open, unresolved
# Cursor forum report of sessionStart's additional_context never reaching
# the model's initial context on some versions, and the hook is documented
# to run fire-and-forget (Cursor does not wait for it), so even a correct
# response can lose a race with the first turn. The confirmed-safe delivery
# path is sync-cursor-rules.sh (static .cursor/rules/*.mdc) — use that
# unless you have specifically verified this hook works on your version.
#
# Cursor's sessionStart wire format (per current docs/community reporting,
# not independently confirmed the way Claude Code's and Devin's hooks were —
# see README.md): reads a JSON payload on stdin (workspace_roots among its
# fields), and expects {"additional_context": "..."} on stdout.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$STDIN_JSON" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print('')
    raise SystemExit
roots = data.get('workspace_roots') or []
print(roots[0] if roots else data.get('cwd', ''))
" 2>/dev/null || true)"
[ -n "$CWD" ] || CWD="$(pwd)"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METHOD_DIR="$(cd "$HERE/../../method" && pwd)"
HEADER_SCRIPT="$METHOD_DIR/protocol-header.sh"

find_project_protocol() {
  _d="$1"
  while [ -n "$_d" ] && [ "$_d" != "/" ]; do
    if [ -f "$_d/SCIENTIFIC_PROTOCOL.md" ]; then
      printf '%s\n' "$_d/SCIENTIFIC_PROTOCOL.md"
      return 0
    fi
    _d="$(dirname "$_d")"
  done
  return 1
}

PROTOCOL="$(find_project_protocol "$CWD" || true)"
CONTEXT=""
if [ -n "$PROTOCOL" ] && [ -f "$PROTOCOL" ]; then
  "$HEADER_SCRIPT" sync "$PROTOCOL" >/dev/null 2>&1 || true
  CONTEXT="$("$HEADER_SCRIPT" emit "$PROTOCOL" 2>/dev/null || echo "Header unavailable; read $PROTOCOL directly.")"
fi

python3 -c "
import json, sys
print(json.dumps({'additional_context': sys.argv[1]}))
" "$CONTEXT"
