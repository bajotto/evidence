#!/usr/bin/env bash
# test-protocol-mcp-server.sh — protocol-level tests for protocol_mcp_server.py.
# Drives the server with real JSON-RPC 2.0 messages over stdio (the exact
# framing MCP's 2024-11-05 spec requires: newline-delimited, no headers) and
# asserts on its responses. No MCP client library, no Cursor/Codex/Trae
# install needed — this validates the wire protocol directly, the same way
# claude/hooks/test-hooks.sh validates hook JSON without a real Claude Code
# session.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/protocol_mcp_server.py"
TEMPLATE="$HERE/../PROJECT_PROTOCOL_TEMPLATE.md"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

PROJ="$(mktemp -d)"
trap 'rm -rf "$PROJ"' EXIT
cp "$TEMPLATE" "$PROJ/SCIENTIFIC_PROTOCOL.md"

run_session() {
  python3 "$SERVER"
}

OUT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"protocol_header\",\"arguments\":{\"project_path\":\"$PROJ\"}}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"protocol_search\",\"arguments\":{\"project_path\":\"$PROJ\",\"mode\":\"hypotheses\"}}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"protocol_search\",\"arguments\":{\"project_path\":\"$PROJ\",\"mode\":\"grep\",\"pattern\":\"pilot\"}}}" \
  "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"tools/call\",\"params\":{\"name\":\"protocol_search\",\"arguments\":{\"project_path\":\"$PROJ\",\"mode\":\"grep\"}}}" \
  '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"nonexistent_tool","arguments":{}}}' \
  'not even json' \
  '{"jsonrpc":"2.0","id":7,"method":"unknown/method"}' \
  "{\"jsonrpc\":\"2.0\",\"id\":8,\"method\":\"tools/call\",\"params\":{\"name\":\"protocol_header\",\"arguments\":{\"project_path\":\"/no/such/project\"}}}" \
  | run_session)"

get_line() { echo "$OUT" | python3 -c "
import json, sys
target = int(sys.argv[1])
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if msg.get('id') == target:
        print(json.dumps(msg))
        break
" "$1"; }

# --- initialize handshake ---
L1="$(get_line 1)"
echo "$L1" | grep -q '"protocolVersion": "2024-11-05"' && pass "initialize echoes protocolVersion" || fail "initialize missing protocolVersion"
echo "$L1" | grep -q '"serverInfo"' && pass "initialize returns serverInfo" || fail "initialize missing serverInfo"

# --- notifications/initialized produces no response line ---
echo "$OUT" | grep -q 'notifications/initialized' && fail "server echoed the initialized notification (should be silent)" \
                                                    || pass "notifications/initialized produced no output (correctly silent)"

# --- tools/list ---
L2="$(get_line 2)"
echo "$L2" | grep -q '"protocol_header"' && pass "tools/list includes protocol_header" || fail "tools/list missing protocol_header"
echo "$L2" | grep -q '"protocol_search"' && pass "tools/list includes protocol_search" || fail "tools/list missing protocol_search"
echo "$L2" | grep -q '"inputSchema"' && pass "tools/list entries have inputSchema" || fail "tools/list entries missing inputSchema"

# --- tools/call protocol_header ---
L3="$(get_line 3)"
echo "$L3" | grep -q 'PROTOCOL HEADER' && pass "protocol_header returns the actual header text" || fail "protocol_header did not return header text"
echo "$L3" | grep -q '"isError": true' && fail "protocol_header reported isError on a valid project" || pass "protocol_header did not report isError on a valid project"

# --- tools/call protocol_search hypotheses ---
L4="$(get_line 4)"
echo "$L4" | grep -q 'H1' && pass "protocol_search hypotheses returns H1" || fail "protocol_search hypotheses missing H1"

# --- tools/call protocol_search grep ---
L5="$(get_line 5)"
echo "$L5" | grep -q 'Phase 2' && pass "protocol_search grep finds a real match with section context" || fail "protocol_search grep did not return expected match"

# --- tools/call protocol_search grep with missing required 'pattern' ---
L9="$(get_line 9)"
echo "$L9" | grep -q '"isError": true' && pass "protocol_search grep without pattern reports isError" || fail "protocol_search grep without pattern did not report isError"

# --- unknown tool name ---
L6="$(get_line 6)"
echo "$L6" | grep -q '"error"' && pass "unknown tool name returns a JSON-RPC error" || fail "unknown tool name did not return an error"

# --- malformed JSON line does not kill the server (session continues past it) ---
L7="$(get_line 7)"
echo "$L7" | grep -q '"error"' && pass "server survives a malformed line and answers the next request" || fail "server did not recover after a malformed line"

# --- protocol_header on a path with no SCIENTIFIC_PROTOCOL.md ---
L8="$(get_line 8)"
echo "$L8" | grep -q '"isError": true' && pass "protocol_header reports isError when no protocol file exists" || fail "protocol_header did not report isError for a missing protocol"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
