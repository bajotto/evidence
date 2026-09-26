#!/usr/bin/env bash
# Sets up Cursor delivery for one project: the confirmed-safe static rule
# (.cursor/rules/scientific-method.mdc) plus service-mode MCP registration.
# Does NOT install the sessionStart hook — see hooks/session-start-protocol.sh
# and README.md for why that one is opt-in only.
#
# Usage: ./install.sh PROJECT_DIR
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: ./install.sh PROJECT_DIR" >&2
  exit 2
fi
PROJECT_DIR="$(cd "$1" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METHOD_DIR="$(cd "$SCRIPT_DIR/../method" && pwd)"

# 1. Static rule — the confirmed-safe path, no known upstream bugs.
bash "$SCRIPT_DIR/hooks/sync-cursor-rules.sh" "$PROJECT_DIR"

# 2. Service-mode MCP registration, project-scoped (.cursor/mcp.json next to
#    the rule, not global — a project can be opened by people who don't all
#    want this server available everywhere).
python3 "$SCRIPT_DIR/hooks/write-cursor-mcp-config.py" \
  "$PROJECT_DIR/.cursor/mcp.json" \
  "$METHOD_DIR/service/protocol_mcp_server.py"

if [ ! -f "$PROJECT_DIR/SCIENTIFIC_PROTOCOL.md" ]; then
  echo
  echo "NOTE: no SCIENTIFIC_PROTOCOL.md in $PROJECT_DIR yet — copy"
  echo "      $METHOD_DIR/PROJECT_PROTOCOL_TEMPLATE.md there and fill it in."
  echo "      Re-run this script afterward to pick up its real content."
fi

echo
cat <<EOF
Done. Not installed by this script, on purpose — see README.md:
- .cursor/hooks.json sessionStart (hooks/session-start-protocol.sh): known
  upstream reports of additional_context not reaching the model on some
  versions. Wire it yourself only after you've verified it works for you.
EOF
