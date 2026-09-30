#!/usr/bin/env bash
# test-protocol-header.sh — regression tests for protocol-header.sh.
# Run: bash method/test-protocol-header.sh
# No framework — just assertions against real output, same style as
# claude/hooks/test-hooks.sh and method/test-protocol-search.sh.
#
# Covers real bugs found running this script for real, not by reading it:
#   1. An f-string with a backslash inside its expression part is a
#      SyntaxError before Python 3.12 (PEP 701 lifted that restriction).
#      Every command (sync/check/emit/hook) crashed on any protocol that
#      actually contains a "### Phase N" heading.
#   2. sync() checked `text.startswith(START)` to decide whether a header
#      already existed. The project's own template — and any real protocol
#      copied from it — carries prose before the header, so the check was
#      always false there, and sync() prepended a second header on top of
#      the first instead of replacing it in place.
#   3. emit printed file-start..END instead of START..END, leaking that same
#      preamble into every hook injection.
#   4. project_name() returned the wrong regex group, so **Project:** showed
#      the generic "Evidence Protocol" title suffix instead of the actual
#      project name, for every protocol following the template's own title
#      convention.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HEADER="$HERE/protocol-header.sh"
TEMPLATE="$HERE/PROJECT_PROTOCOL_TEMPLATE.md"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

FIXTURE="$(mktemp)"
trap 'rm -f "$FIXTURE" "$FIXTURE.tmp"' EXIT
cp "$TEMPLATE" "$FIXTURE"

# --- bug 1 regression: a Phase heading must not crash sync/check/emit ---
"$HEADER" sync "$FIXTURE" >/dev/null 2>&1
[ $? -eq 0 ] && pass "sync does not crash on a protocol with Phase headings (f-string regression)" \
             || fail "sync crashed on a protocol with Phase headings (f-string regression)"

# --- bug 2 regression: the template has prose before the header; sync must ---
# --- replace the existing header in place, not add a second one on top ---
STARTS=$(grep -c 'PROTOCOL-HEADER:START' "$FIXTURE")
ENDS=$(grep -c 'PROTOCOL-HEADER:END' "$FIXTURE")
[ "$STARTS" -eq 1 ] && pass "exactly one START marker after sync (no duplicate header)" \
                     || fail "found $STARTS START markers after sync (duplicate-header regression)"
[ "$ENDS" -eq 1 ] && pass "exactly one END marker after sync" \
                   || fail "found $ENDS END markers after sync"

# --- prose before the header must survive the replace ---
grep -q "Copy this file into the root of your project" "$FIXTURE" \
  && pass "prose preceding the header is preserved, not discarded" \
  || fail "prose preceding the header was lost"

# --- check must pass on the freshly synced file ---
"$HEADER" check "$FIXTURE" >/dev/null 2>&1
[ $? -eq 0 ] && pass "check passes on a freshly synced protocol" || fail "check failed on a freshly synced protocol"

# --- sync must be idempotent: a second run changes nothing ---
BEFORE_HASH=$(sha256sum "$FIXTURE" | cut -d' ' -f1)
OUT=$("$HEADER" sync "$FIXTURE" 2>&1)
AFTER_HASH=$(sha256sum "$FIXTURE" | cut -d' ' -f1)
[ "$BEFORE_HASH" = "$AFTER_HASH" ] && pass "sync is idempotent (second run is a no-op)" \
                                    || fail "sync is not idempotent (second run changed the file)"
echo "$OUT" | grep -q "UNCHANGED" && pass "sync reports UNCHANGED on the idempotent run" \
                                   || fail "sync did not report UNCHANGED on the idempotent run"

# --- emit must return only the header block, not file-start..END (the template ---
# --- itself carries prose before the header, which used to leak into every hook) ---
EMIT_OUT=$("$HEADER" emit "$FIXTURE" 2>&1)
echo "$EMIT_OUT" | grep -q "Copy this file into the root of your project" \
  && fail "emit leaked the prose preceding the header" \
  || pass "emit does not leak the prose preceding the header"
echo "$EMIT_OUT" | head -1 | grep -q "PROTOCOL-HEADER:START" \
  && pass "emit's first line is the header START marker" \
  || fail "emit's first line is not the header START marker"

# --- phase index must list real titles, not raise, and use correct line numbers ---
OUT=$("$HEADER" emit "$FIXTURE" 2>&1)
echo "$OUT" | grep -q "Phase 1 — Discovery (line" && pass "phase index lists Phase 1 with a line number" \
                                                    || fail "phase index missing Phase 1 entry"
echo "$OUT" | grep -q "Phase 2 — Pilot (line" && pass "phase index lists Phase 2 with a line number" \
                                               || fail "phase index missing Phase 2 entry"

# --- Project: must be the actual project name, not the generic title suffix ---
# The template's own title is "# [PROJECT_NAME] — Evidence Protocol" (project
# name first, generic suffix second); project_name() returned the wrong regex
# group and reported "Evidence Protocol" itself as **Project:** for every
# protocol following that convention, regardless of the real project name.
echo "$OUT" | grep -q '\*\*Project:\*\* \[PROJECT_NAME\]$' && pass "Project: reports the actual project name" \
                                                            || fail "Project: reports the generic title suffix instead of the project name"

# --- hook must find EVIDENCE_PROTOCOL.md from a subdirectory (it only checked $CWD) ---
TREE="$(mktemp -d)"
trap 'rm -rf "$TREE"; rm -f "$FIXTURE" "$FIXTURE.tmp"' EXIT
mkdir -p "$TREE/sub/deeper"
cp "$FIXTURE" "$TREE/EVIDENCE_PROTOCOL.md"
HOOK_OUT=$(printf '{"cwd":"%s","hook_event_name":"UserPromptSubmit"}' "$TREE/sub/deeper" | "$HEADER" hook 2>&1)
echo "$HOOK_OUT" | grep -q "PROTOCOL-HEADER:START" \
  && pass "hook finds the protocol from a subdirectory of the project" \
  || fail "hook injected nothing from a subdirectory of the project"

# --- Now block is injected, and a stale 'as of' date is flagged against the newest log entry ---
printf '\n<!-- PROTOCOL-NOW:START -->\n- As of 2000-01-01. Marker-now-line.\n<!-- PROTOCOL-NOW:END -->\n\n## 9. LINE CHECK\n\n2026-01-02 — newest entry\n' >> "$TREE/EVIDENCE_PROTOCOL.md"
"$HEADER" sync "$TREE/EVIDENCE_PROTOCOL.md" >/dev/null 2>&1
OUT=$("$HEADER" emit "$TREE/EVIDENCE_PROTOCOL.md" 2>&1)
echo "$OUT" | grep -q "Marker-now-line" && pass "Now block is injected into the header" \
                                        || fail "Now block missing from the header"
echo "$OUT" | grep -q "NOW block is as of 2000-01-01 but the log has an entry from 2026-01-02" \
  && pass "stale Now block is flagged against the newest log entry" \
  || fail "stale Now block was not flagged"
echo "$OUT" | grep -q "2026-01-02 — newest entry (line" && pass "recent log lists the dated entry" \
                                                        || fail "recent log missing the dated entry"

# --- line numbers in the header are real file lines, not body offsets ---
N=$(echo "$OUT" | sed -n 's/^- 9\. LINE CHECK (line \([0-9]*\))$/\1/p')
[ -n "$N" ] && [ "$(sed -n "${N}p" "$TREE/EVIDENCE_PROTOCOL.md")" = "## 9. LINE CHECK" ] \
  && pass "header line numbers point at the real file line" \
  || fail "header line number ${N:-<none>} does not point at '## 9. LINE CHECK'"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
