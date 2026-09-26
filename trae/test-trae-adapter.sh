#!/usr/bin/env bash
# test-trae-adapter.sh — regression tests for sync-trae-rules.sh and
# write-trae-mcp-config.py. No framework — same assertion style as
# method/test-protocol-header.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SYNC="$HERE/hooks/sync-trae-rules.sh"
MCP_WRITER="$HERE/hooks/write-trae-mcp-config.py"
TEMPLATE="$HERE/../method/PROJECT_PROTOCOL_TEMPLATE.md"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

PROJ="$(mktemp -d)"
trap 'rm -rf "$PROJ"' EXIT
cp "$TEMPLATE" "$PROJ/SCIENTIFIC_PROTOCOL.md"

# --- sync-trae-rules.sh: generates a valid rule with required frontmatter ---
bash "$SYNC" "$PROJ" >/dev/null
RULE="$PROJ/.trae/rules/scientific-method.md"
[ -f "$RULE" ] && pass "rule file created" || fail "rule file not created"
head -1 "$RULE" | grep -q '^---$' && pass "rule file starts with frontmatter delimiter" || fail "rule file missing frontmatter delimiter"
grep -q '^alwaysApply: true$' "$RULE" && pass "rule file declares alwaysApply: true" || fail "rule file missing alwaysApply: true"

grep -q "Copy this file into the root of your project" "$RULE" \
  && fail "rule file leaked the protocol template's preamble" \
  || pass "rule file does not leak the protocol template's preamble"

BEFORE=$(sha256sum "$RULE" | cut -d' ' -f1)
OUT=$(bash "$SYNC" "$PROJ")
AFTER=$(sha256sum "$RULE" | cut -d' ' -f1)
[ "$BEFORE" = "$AFTER" ] && pass "sync-trae-rules.sh is idempotent" || fail "sync-trae-rules.sh changed output on a second run"
echo "$OUT" | grep -q "UNCHANGED" && pass "second run reports UNCHANGED" || fail "second run did not report UNCHANGED"

# --- write-trae-mcp-config.py: creates valid JSON with mcpServers ---
MCP_JSON="$PROJ/.trae/mcp.json"
python3 "$MCP_WRITER" "$MCP_JSON" /fake/path/protocol_mcp_server.py >/dev/null
python3 -c "
import json
data = json.load(open('$MCP_JSON'))
assert 'scientific-method' in data['mcpServers'], 'missing scientific-method entry'
assert data['mcpServers']['scientific-method']['command'] == 'python3'
" && pass "mcp.json has correctly-shaped scientific-method entry" || fail "mcp.json entry malformed"

python3 -c "
import json
data = json.load(open('$MCP_JSON'))
data['mcpServers']['other-server'] = {'command': 'node', 'args': ['/x.js']}
json.dump(data, open('$MCP_JSON', 'w'))
"
python3 "$MCP_WRITER" "$MCP_JSON" /fake/path/protocol_mcp_server.py >/dev/null
python3 -c "
import json
data = json.load(open('$MCP_JSON'))
assert 'other-server' in data['mcpServers'], 'other-server entry was dropped'
assert 'scientific-method' in data['mcpServers']
" && pass "mcp.json writer preserves a pre-existing unrelated server entry" || fail "mcp.json writer dropped a pre-existing entry"

OUT=$(python3 "$MCP_WRITER" "$MCP_JSON" /fake/path/protocol_mcp_server.py)
echo "$OUT" | grep -q "UNCHANGED" && pass "mcp.json writer is idempotent" || fail "mcp.json writer is not idempotent"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
