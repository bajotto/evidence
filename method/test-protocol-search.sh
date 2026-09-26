#!/usr/bin/env bash
# test-protocol-search.sh — self-check for protocol-search.sh.
# Run: bash method/test-protocol-search.sh
# No framework, no fixtures beyond a generated temp file — just assertions
# against real output, same style as claude/hooks/test-hooks.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SEARCH="$HERE/protocol-search.sh"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

FIXTURE="$(mktemp)"
trap 'rm -f "$FIXTURE"' EXIT

cat > "$FIXTURE" <<'EOF'
<!-- PROTOCOL-HEADER:START -->
# PROTOCOL HEADER — READ FIRST
**Current phase:** 2
<!-- PROTOCOL-HEADER:END -->

# demo-project — Scientific Protocol

## 1. Testable hypotheses

### H1: no duplicate sends
- **H0 (null):** the system can send the same message twice
- **H1 (alternative):** every recipient gets at most one message
- **Acceptance criterion:** 0 duplicate sends across 100% of history
- **Status:** ✅ validated (12/12, 2026-08-01)

### H2: no broken placeholders
- **H0 (null):** rendered messages contain an unresolved placeholder
- **H1 (alternative):** 100% of messages render clean
- **Acceptance criterion:** 0 occurrences of `{{` in sent output
- **Status:** ⏳ not yet tested

### H3: long preceding bullets must not push Status out of reach
- **H0 (null):** a hypothesis whose H0/H1/acceptance-criterion bullets each
  wrap across several physical lines pushes the Status bullet far enough
  down that a fixed-size lookahead window misses it entirely.
- **H1 (alternative):** Status is found and its own wrapped continuation
  lines are joined into one line, regardless of how long the bullets
  before it are.
- **Acceptance criterion:** this exact case (three multi-line bullets
  before Status, and Status itself wrapping across three lines) resolves
  to a single joined line, not "(not stated)".
- **Status:** ✅ validated — this status line itself wraps across three
  physical lines in the source file, on purpose, to exercise exactly the
  continuation logic being tested here, ending with a closing marker:
  STATUS_END_MARKER

## 2. Phases

### Phase 1 — Discovery
**Goal:** understand current state, no execution.
**Status:** complete, 2026-07-20
**Findings:** 340 candidate recipients, 12 flagged as duplicates upstream.

### Phase 2 — Pilot
**Goal:** validate hypotheses against 3-5 real cases.
**Status:** complete, 2026-08-01
**Result:** 12/12 pass
**Approval to scale:** granted, pedro, 2026-08-02

## 3. Incident log

### Incident: 2026-08-15
**What happened:** two messages sent to the same recipient within 4 seconds.
**Root cause:** retry logic did not check a send-in-flight marker.

### Incident: 2026-09-01
**What happened:** a template rendered with a literal `{{name}}` placeholder.
**Root cause:** the render step was skipped for one message class.
EOF

# --- grep: finds a term with section context ---
OUT="$("$SEARCH" grep "$FIXTURE" "duplicate")"
echo "$OUT" | grep -q "H1: no duplicate sends" && pass "grep finds match under correct section" \
                                                || fail "grep did not report enclosing section"
echo "$OUT" | grep -q "match(es)" && pass "grep reports match count" || fail "grep missing match count"

# --- grep: no match exits 1 ---
"$SEARCH" grep "$FIXTURE" "no_such_term_anywhere" >/dev/null 2>&1
[ $? -eq 1 ] && pass "grep exits 1 on no match" || fail "grep did not exit 1 on no match"

# --- hypotheses: lists both, with status ---
OUT="$("$SEARCH" hypotheses "$FIXTURE")"
echo "$OUT" | grep -q "H1: no duplicate sends" && pass "hypotheses lists H1" || fail "hypotheses missing H1"
echo "$OUT" | grep -q "H2: no broken placeholders" && pass "hypotheses lists H2" || fail "hypotheses missing H2"
echo "$OUT" | grep -q "validated (12/12, 2026-08-01)" && pass "hypotheses shows H1 status" \
                                                       || fail "hypotheses did not show H1 status"
echo "$OUT" | grep -q "not yet tested" && pass "hypotheses shows H2 status" || fail "hypotheses did not show H2 status"

# --- hypotheses: a status wrapped across physical lines, behind long ---
# --- preceding bullets, is still found and joined onto one line ---
echo "$OUT" | grep -q "H3: long preceding bullets" && pass "hypotheses lists H3" || fail "hypotheses missing H3"
H3_LINE=$(echo "$OUT" | grep "STATUS_END_MARKER")
[ -n "$H3_LINE" ] && pass "hypotheses joins a multi-line H3 status onto one line" \
                   || fail "hypotheses truncated a multi-line status (regression)"
echo "$H3_LINE" | grep -qv "^     Status: (not stated)$" && pass "H3 status is not '(not stated)'" \
                                                           || fail "H3 status incorrectly shows '(not stated)'"

# --- incidents: lists both ---
OUT="$("$SEARCH" incidents "$FIXTURE")"
echo "$OUT" | grep -q "2026-08-15" && pass "incidents lists first incident" || fail "incidents missing first"
echo "$OUT" | grep -q "2026-09-01" && pass "incidents lists second incident" || fail "incidents missing second"

# --- incidents: filters by pattern ---
OUT="$("$SEARCH" incidents "$FIXTURE" "placeholder")"
echo "$OUT" | grep -q "2026-09-01" && pass "incidents filter matches the right one" || fail "incidents filter missed match"
echo "$OUT" | grep -q "2026-08-15" && fail "incidents filter over-matched" || pass "incidents filter excludes non-matching entry"

# --- incidents: no match exits 1 ---
"$SEARCH" incidents "$FIXTURE" "no_such_term_anywhere" >/dev/null 2>&1
[ $? -eq 1 ] && pass "incidents exits 1 on no match" || fail "incidents did not exit 1 on no match"

# --- phase: extracts only the requested phase, stops at next heading ---
OUT="$("$SEARCH" phase "$FIXTURE" 1)"
echo "$OUT" | grep -q "340 candidate recipients" && pass "phase 1 includes its own findings" \
                                                  || fail "phase 1 missing its findings"
echo "$OUT" | grep -q "Approval to scale" && fail "phase 1 leaked into phase 2 content" \
                                          || pass "phase 1 stops before phase 2 content"

# --- phase: unknown phase exits 1 ---
"$SEARCH" phase "$FIXTURE" 99 >/dev/null 2>&1
[ $? -eq 1 ] && pass "phase exits 1 for a phase that does not exist" || fail "phase did not exit 1 for missing phase"

# --- header is excluded from search (it's a derived summary, not body content) ---
OUT="$("$SEARCH" grep "$FIXTURE" "PROTOCOL HEADER" 2>&1)"
echo "$OUT" | grep -q "No matches" && pass "grep does not search inside the header block" \
                                    || fail "grep leaked into the header block"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
