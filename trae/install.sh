#!/usr/bin/env bash
# Sets up Trae IDE delivery for one project: static rules
# (.trae/rules/scientific-method.md) plus service-mode MCP registration.
# Trae has no documented hook/session-start mechanism at all (confirmed
# absent, not just unverified — see README.md), so unlike claude/, devin/,
# codex/, and cursor/, there is no "optional hook, opt in yourself" section
# here — static rules are the whole standalone-mode story for Trae.
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

bash "$SCRIPT_DIR/hooks/sync-trae-rules.sh" "$PROJECT_DIR"

python3 "$SCRIPT_DIR/hooks/write-trae-mcp-config.py" \
  "$PROJECT_DIR/.trae/mcp.json" \
  "$METHOD_DIR/service/protocol_mcp_server.py"

if [ ! -f "$PROJECT_DIR/SCIENTIFIC_PROTOCOL.md" ]; then
  echo
  echo "NOTE: no SCIENTIFIC_PROTOCOL.md in $PROJECT_DIR yet — copy"
  echo "      $METHOD_DIR/PROJECT_PROTOCOL_TEMPLATE.md there and fill it in."
  echo "      Re-run this script afterward to pick up its real content."
fi

echo
echo "Done. See README.md for what's confirmed vs. documentation-only for Trae."
