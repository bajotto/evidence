#!/usr/bin/env bash
# test-hooks.sh — self-check for the two hook scripts.
# Run: bash ~/.claude/hooks/test-hooks.sh
# Exits 0 if all assertions pass, 1 on first failure.
# No framework, no fixtures — just assertions against real output.
set -uo pipefail

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"
SYNC="$HOOKS_DIR/sync-windsurf-rules.sh"
SESSION_START="$HOOKS_DIR/session-start-protocol-global.sh"
GLOBAL_RULES="/home/main/.codeium/windsurf/memories/global_rules.md"

PASS=0
FAIL=0
fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }
pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
assert_contains() { grep -q "$2" "$1" && pass "$3" || fail "$3"; }
assert_not_contains() { ! grep -q "$2" "$1" && pass "$3" || fail "$3"; }

# --- 1. sync-windsurf-rules.sh: no empty sections (Bug 1 regression) ---
# An empty section looks like "### Title\n\n### Next" — grep for two headers
# separated only by a blank line. If extract_section returns nothing, the
# section header is immediately followed by another header.
bash "$SYNC" >/dev/null 2>&1
EMPTY_SECTIONS=$(grep -c '^### .*$$' "$GLOBAL_RULES" | head -1)
# Better: count headers, then count headers that are followed (within 2 lines)
# by another header with no content between.
EMPTY=$(awk '/^### / { h=NR; next } h && NR==h+1 && /^### / { print "empty at "h }' "$GLOBAL_RULES" | wc -l)
[ "$EMPTY" -eq 0 ] && pass "no empty sections in global_rules.md" \
                   || fail "$EMPTY empty sections in global_rules.md (Bug 1 regression)"

# --- 2. sync-windsurf-rules.sh: each section has real content ---
# Bug 1 failure mode: a generated "### X" header immediately followed by
# the next generated "### Y" header with no non-blank lines between.
# Source content may itself start with "##" or "###" (from the canonical MDs),
# so we check for non-blank lines between consecutive GENERATED section headers.
SECTIONS=("Session start" "Phase gates" "Approval gates" "No shortcuts" "Multi-server tasks" "Method: hypotheses")
for i in "${!SECTIONS[@]}"; do
  section="${SECTIONS[$i]}"
  LINE=$(grep -n "### $section" "$GLOBAL_RULES" | cut -d: -f1 | head -1)
  if [ -z "$LINE" ]; then
    fail "section '$section' header not found"
    continue
  fi
  # Find the next generated section header line
  NEXT_GEN_LINE=$(echo "0")
  for j in $(seq $((i+1)) $((${#SECTIONS[@]}-1))); do
    NEXT_SECTION="${SECTIONS[$j]}"
    NSL=$(grep -n "### $NEXT_SECTION" "$GLOBAL_RULES" | cut -d: -f1 | head -1)
    if [ -n "$NSL" ] && [ "$NSL" -gt "$LINE" ]; then
      NEXT_GEN_LINE="$NSL"
      break
    fi
  done
  # Count non-blank lines between this header and the next generated header (or EOF)
  if [ "$NEXT_GEN_LINE" -eq 0 ]; then
    CONTENT_LINES=$(sed -n "$((LINE+1)),\$p" "$GLOBAL_RULES" | grep -cv '^$')
  else
    CONTENT_LINES=$(sed -n "$((LINE+1)),$((NEXT_GEN_LINE-1))p" "$GLOBAL_RULES" | grep -cv '^$')
  fi
  [ "$CONTENT_LINES" -gt 0 ] \
    && pass "section '$section' has $CONTENT_LINES content lines" \
    || fail "section '$section' empty (0 non-blank lines before next generated header)"
done

# --- 3. sync-windsurf-rules.sh: auto-discovers projects (Bug 2 regression) ---
# Re-run and capture stdout, count "=== Project:" lines
OUTPUT=$(bash "$SYNC" 2>/dev/null)
PROJECT_COUNT=$(echo "$OUTPUT" | grep -c '=== Project:')
[ "$PROJECT_COUNT" -ge 5 ] && pass "auto-discovered $PROJECT_COUNT projects (>=5)" \
                            || fail "only $PROJECT_COUNT projects discovered (Bug 2 regression)"

# --- 4. session-start-protocol-global.sh: produces valid JSON ---
JSON=$(echo '{"cwd":"/home/main/code/evidence"}' | bash "$SESSION_START" 2>/dev/null)
echo "$JSON" | jq -e '.hookSpecificOutput.hookEventName == "SessionStart"' >/dev/null 2>&1 \
  && pass "session-start produces valid JSON with SessionStart event" \
  || fail "session-start JSON invalid"

# --- 5. session-start-protocol-global.sh: injects the canonical docs ---
CONTEXT=$(echo "$JSON" | jq -r '.hookSpecificOutput.additionalContext')
case "$CONTEXT" in
  *EVIDENCE.md*) pass "session-start injects EVIDENCE.md";;
  *) fail "session-start missing EVIDENCE.md injection";;
esac

# --- 6. protocol-header.sh: generates a bounded, readable, indexed header ---
HEADER="$HOOKS_DIR/protocol-header.sh"
FIXTURE=$(mktemp)
cp /home/main/code/managd/EVIDENCE_PROTOCOL.md "$FIXTURE"
BEFORE=$(sha256sum "$FIXTURE" | cut -d' ' -f1)
bash "$HEADER" sync "$FIXTURE" >/dev/null 2>&1 && pass "header sync succeeds" || fail "header sync failed"
bash "$HEADER" check "$FIXTURE" >/dev/null 2>&1 && pass "header check succeeds" || fail "header check failed"
grep -q '## Phase index' "$FIXTURE" && pass "header has phase index" || fail "header missing phase index"
grep -q '## Body index' "$FIXTURE" && pass "header has body index" || fail "header missing body index"
AFTER=$(sha256sum "$FIXTURE" | cut -d' ' -f1)
bash "$HEADER" sync "$FIXTURE" >/dev/null 2>&1
AFTER2=$(sha256sum "$FIXTURE" | cut -d' ' -f1)
[ "$AFTER" = "$AFTER2" ] && pass "header sync is idempotent" || fail "header sync is not idempotent"
rm -f "$FIXTURE"

# --- 7. protocol-header.sh: injects current state on every prompt ---
PROMPT_JSON=$(printf '%s' '{"cwd":"/home/main/code/jobs-agent","hook_event_name":"UserPromptSubmit"}' | bash "$HEADER" hook 2>/dev/null)
PROMPT_CONTEXT=$(echo "$PROMPT_JSON" | jq -r '.hookSpecificOutput.additionalContext')
echo "$PROMPT_JSON" | jq -e '.hookSpecificOutput.hookEventName == "UserPromptSubmit"' >/dev/null 2>&1 \
  && pass "UserPromptSubmit produces valid hook output" || fail "UserPromptSubmit output invalid"
case "$PROMPT_CONTEXT" in
  *'Current status (body)'*'## Phase index'*) pass "prompt injection contains current status and phase index";;
  *) fail "prompt injection missing current status or phase index";;
esac

# --- 8. protocol-header.sh: PostToolUse auto-syncs protocol edits ---
POST_FIXTURE=$(mktemp)
cp /home/main/code/managd/EVIDENCE_PROTOCOL.md "$POST_FIXTURE"
rm -f "$POST_FIXTURE.tmp"
printf '%s' "{\"cwd\":\"/tmp\",\"hook_event_name\":\"PostToolUse\",\"tool_name\":\"edit\",\"tool_input\":{\"file_path\":\"$POST_FIXTURE\"}}" | bash "$HEADER" hook >/dev/null 2>&1
bash "$HEADER" check "$POST_FIXTURE" >/dev/null 2>&1 && pass "PostToolUse keeps edited protocol valid" || fail "PostToolUse did not validate protocol"
rm -f "$POST_FIXTURE"

# --- 9. session-start-protocol-global.sh: current header replaces body cap ---
JOBS_JSON=$(echo '{"cwd":"/home/main/code/jobs-agent"}' | bash "$SESSION_START" 2>/dev/null)
JOBS_CONTEXT=$(echo "$JOBS_JSON" | jq -r '.hookSpecificOutput.additionalContext')
case "$JOBS_CONTEXT" in
  *'CURRENT PROTOCOL HEADER'*'## Phase index'*) pass "SessionStart injects readable header for large protocol";;
  *) fail "SessionStart missing readable header for large protocol";;
esac
JOBS_SIZE=$(echo -n "$JOBS_CONTEXT" | wc -c)
[ "$JOBS_SIZE" -lt 30000 ] && pass "SessionStart context is bounded (${JOBS_SIZE} bytes)" || fail "SessionStart context unexpectedly large (${JOBS_SIZE} bytes)"

# --- 10. session-start-protocol-global.sh: uses mktemp, not hardcoded /tmp path (Issue 4) ---
assert_not_contains "$SESSION_START" '/tmp/session-state.err' "no hardcoded /tmp/session-state.err path"
assert_contains "$SESSION_START" 'mktemp' "uses mktemp for state error file"

# --- 8. session-start-protocol-global.sh: documents trust assumption (Issue 6) ---
assert_contains "$SESSION_START" 'TRUST ASSUMPTION' "documents session-state.sh RCE trust assumption"

# --- 9. sync-windsurf-rules.sh: log rotation present (Issue 3) ---
assert_contains "$SYNC" '1048576' "log rotation at 1MB threshold"
assert_contains "$SYNC" 'LOG_FILE.1' "log rotates to .log.1"

# --- 10. sync-windsurf-rules.sh: extract_section (not extract_h2) ---
assert_contains "$SYNC" 'extract_section' "uses extract_section (not broken extract_h2)"
assert_not_contains "$SYNC" 'extract_h2' "no leftover extract_h2 references"

echo ""
# --- N. Protocol discovered from a subdirectory (regression) ---
# The hook used to resolve the protocol as "$CWD/EVIDENCE_PROTOCOL.md" with no
# walk up the tree. A session started in any subdirectory of the repo (server/,
# web/, a monorepo package) got no protocol at all — and got it silently, so the
# session ran with no phase, status or open hypotheses.
PROTO_TMP="$(mktemp -d)"
mkdir -p "$PROTO_TMP/proj/a/b"
cp "$HOOKS_DIR/../../method/PROJECT_PROTOCOL_TEMPLATE.md" "$PROTO_TMP/proj/EVIDENCE_PROTOCOL.md" 2>/dev/null \
  || printf '# EVIDENCE_PROTOCOL\n\n**Status:** test\n\n## 3. PHASES\n\nPhase 1.\n' > "$PROTO_TMP/proj/EVIDENCE_PROTOCOL.md"

for depth in "proj" "proj/a" "proj/a/b"; do
  OUT=$(cd "$PROTO_TMP/$depth" && echo '{}' | timeout 20 bash "$SESSION_START" 2>/dev/null)
  echo "$OUT" | grep -q "CURRENT PROTOCOL" \
    && pass "protocol found from $depth" \
    || fail "protocol NOT found from $depth (subdirectory regression)"
done

# Deepest match wins: a nested protocol must override its parent's.
printf '# nested\n\n**Status:** nested\n' > "$PROTO_TMP/proj/a/EVIDENCE_PROTOCOL.md"
OUT=$(cd "$PROTO_TMP/proj/a/b" && echo '{}' | timeout 20 bash "$SESSION_START" 2>/dev/null)
echo "$OUT" | grep -q "proj/a/EVIDENCE_PROTOCOL.md" \
  && pass "nearest protocol wins over an ancestor's" \
  || fail "nearest protocol did not win over an ancestor's"

# Outside any project it must not invent one.
OUT=$(cd "$PROTO_TMP" && echo '{}' | timeout 20 bash "$SESSION_START" 2>/dev/null)
echo "$OUT" | grep -q "CURRENT PROTOCOL" \
  && fail "claimed a protocol outside any project" \
  || pass "no protocol claimed outside a project"

# --- N+1. protocol-header.sh must not block on stdin (regression) ---
# Line 1 read stdin unconditionally via $(cat), but only hook mode (no
# subcommand) is ever fed JSON there. Any caller that left the pipe open — a
# terminal, or a hook without </dev/null — hung the process until its timeout,
# and the hook swallows that with "|| true", so the header silently went stale.
HDR="$HOOKS_DIR/protocol-header.sh"
for cmd in emit check sync; do
  timeout 8 bash "$HDR" "$cmd" "$PROTO_TMP/proj/EVIDENCE_PROTOCOL.md" < <(sleep 20) >/dev/null 2>&1
  RC=$?
  [ "$RC" -ne 124 ] \
    && pass "protocol-header.sh $cmd does not block on an open stdin" \
    || fail "protocol-header.sh $cmd hung on an open stdin (rc=124)"
done

# Hook mode (no subcommand) must still read its JSON payload from stdin.
echo '{"hook_event_name":"SessionStart"}' | timeout 8 bash "$HDR" >/dev/null 2>&1
[ $? -ne 124 ] && pass "protocol-header.sh hook mode still reads stdin" \
               || fail "protocol-header.sh hook mode broke on stdin"

# --- N+2. method/ copy is executable (README tells you to start there) ---
[ -x "$HOOKS_DIR/../../method/protocol-header.sh" ] \
  && pass "method/protocol-header.sh is executable" \
  || fail "method/protocol-header.sh is not executable"

rm -rf "$PROTO_TMP"

echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
