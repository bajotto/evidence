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
JSON=$(echo '{"cwd":"/home/main/code/scientific-method-ai"}' | bash "$SESSION_START" 2>/dev/null)
echo "$JSON" | jq -e '.hookSpecificOutput.hookEventName == "SessionStart"' >/dev/null 2>&1 \
  && pass "session-start produces valid JSON with SessionStart event" \
  || fail "session-start JSON invalid"

# --- 5. session-start-protocol-global.sh: injects the canonical docs ---
CONTEXT=$(echo "$JSON" | jq -r '.hookSpecificOutput.additionalContext')
case "$CONTEXT" in
  *SCIENTIFIC_METHOD.md*) pass "session-start injects SCIENTIFIC_METHOD.md";;
  *) fail "session-start missing SCIENTIFIC_METHOD.md injection";;
esac

# --- 6. session-start-protocol-global.sh: truncates large protocols (Issue 5) ---
# large-project has a 746KB protocol — should be truncated
JOBS_JSON=$(echo '{"cwd":"/path/to/project"}' | bash "$SESSION_START" 2>/dev/null)
JOBS_CONTEXT=$(echo "$JOBS_JSON" | jq -r '.hookSpecificOutput.additionalContext')
JOBS_SIZE=$(echo -n "$JOBS_CONTEXT" | wc -c)
case "$JOBS_CONTEXT" in
  *TRUNCATED*) [ "$JOBS_SIZE" -lt 120000 ] \
    && pass "large protocol truncated (${JOBS_SIZE} bytes, has TRUNCATED marker)" \
    || fail "truncation marker present but size ${JOBS_SIZE} too large";;
  *) [ -f /path/to/project/SCIENTIFIC_PROTOCOL.md ] \
    && fail "large protocol not truncated (${JOBS_SIZE} bytes, no marker)" \
    || pass "no large-project protocol to test truncation (skipped)";;
esac

# --- 7. session-start-protocol-global.sh: uses mktemp, not hardcoded /tmp path (Issue 4) ---
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
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
