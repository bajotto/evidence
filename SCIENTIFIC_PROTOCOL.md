# scientific-method-ai — Scientific Protocol

This project follows its own method on itself: `method/SCIENTIFIC_METHOD.md`
and `method/ENFORCEMENT_MODEL.md` are the canonical docs; this file is the
running record for the repo's own development, using
`method/PROJECT_PROTOCOL_TEMPLATE.md` as its structure.

<!-- PROTOCOL-HEADER:START -->
# PROTOCOL HEADER — READ FIRST
This is the authoritative current-state summary. The full protocol body is the source of history and evidence.
**Project:** scientific-method-ai
**Current phase:** 4
**Last updated (body):** 2026-09-26
**Current status (body):** Phase 4 (Monitor) — PR #1 open against `main`, all local tests green, watching for CI/review.

## How to use this protocol
1. Treat every claim as H0 (failure mode) vs H1 (expected result).
2. Require a measurable acceptance criterion and record each case pass/fail.
3. Work in order: Discovery → Pilot (3–5 real cases) → approval → Scale → Monitor.
4. Never scale on a partial pilot; document failures and the evidence that resolved them.
5. Read the full body before acting; this header intentionally does not replace history.

## Phase index (details are in the full body)
- Phase 1 — Discovery (line 127)
- Phase 2 — Pilot (line 138)
- Phase 3 — Scale (line 151)
- Phase 4 — Monitor (line 169)
- Current phase details: search the full body for `Phase 4`; line numbers above are body offsets.

## Non-negotiable gates
- Phase 1 is read-only discovery; Phase 2 must test 3–5 real cases.
- Phase 2 must be 100% pass and explicitly approved before Phase 3.
- Phase 3 results must be measured from the real system; Phase 4 monitors outcomes.
- Do not claim production confirmation without running the confirming query.

## Body index
- 1. Testable hypotheses (line 13)
- 2. Phases (line 125)
- 3. Incident log (line 181)
- 4. Checklist for the next session (line 317)

## Full-text search (do not read the whole body just to find one thing)
Installed next to this script (protocol-header.sh) by install.sh — same directory.
- protocol-search.sh hypotheses FILE           — every H<n>, with its Status line
- protocol-search.sh incidents FILE [PATTERN]  — incident log, optionally filtered
- protocol-search.sh phase FILE N              — just that Phase section
- protocol-search.sh grep FILE PATTERN          — free text, with enclosing section

**Next action:** read the body, verify the current phase/status, then state the session start before acting.
<!-- PROTOCOL-HEADER:END -->
**Last updated:** 2026-09-26
**Status:** Phase 4 (Monitor) — PR #1 open against `main`, all local tests green, watching for CI/review.

---

## 1. Testable hypotheses

### H1: full-text search removes the need to read the whole protocol body
- **H0 (null):** An agent must read the entire `SCIENTIFIC_PROTOCOL.md` body
  to answer "what happened in Phase 2" or "has this failure occurred before" —
  infeasible once the body is large (one real project's reached ~722KB).
- **H1 (alternative):** `method/protocol-search.sh`'s four subcommands
  (`hypotheses`, `incidents`, `phase`, `grep`) answer those questions without
  a full read, and the generated `PROTOCOL-HEADER` advertises them so an
  agent that only has the header in context still knows they exist.
- **Acceptance criterion:** each subcommand returns the correct, minimal
  answer on a real fixture; a no-match case exits 1 rather than silently
  succeeding; the header block only, not the body, is ever searched; a
  hypothesis's Status is found and fully joined even when it (or the
  bullets before it) wraps across several physical lines.
- **Status:** ✅ validated (19/19, `method/test-protocol-search.sh`,
  2026-09-26) — the last 3 were added by Incident (f) below, found by
  running `hypotheses` against this very file and getting "(not stated)"
  for four of its six real entries.

### H2: the service-mode MCP server speaks correct MCP without a live client
- **H0 (null):** A hand-rolled MCP server, with no third-party MCP library
  and no way to drive a real Cursor/Codex/Trae session in this environment,
  cannot be verified — "looks right" is not the same as "protocol-correct."
- **H1 (alternative):** Driving the server directly with real JSON-RPC 2.0
  messages over stdio (the exact framing the MCP 2024-11-05 spec requires)
  validates the wire protocol independently of any client: `initialize`,
  `tools/list`, `tools/call` (success and error paths), a malformed input
  line, and a missing-protocol-file case.
- **Acceptance criterion:** 100% of these cases produce the exact
  JSON-RPC shape the spec defines, and the server survives a malformed
  line instead of crashing.
- **Status:** ✅ validated (14/14, `method/service/test-protocol-mcp-server.sh`,
  2026-09-26). **Not validated:** that a real Codex/Cursor/Trae client
  actually spawns the registered server and calls it end-to-end — that
  needs API auth or a live IDE session this environment doesn't have. See
  Phase 4 / next-session checklist.

### H3: Codex CLI's AGENTS.md delivery requires an explicit trust decision
- **H0 (null):** `AGENTS.md` at a project root is read automatically, as
  Codex's own public docs describe, with no further condition.
- **H1 (alternative):** Codex only injects `AGENTS.md` content into the
  model-visible prompt for a project marked `trusted` in
  `~/.codex/config.toml` — an untrusted project gets none of it, with no
  error or warning.
- **Acceptance criterion:** `codex debug prompt-input` on a real
  `codex-cli` install, run twice against the same fixture project (once
  untrusted, once with `-c 'projects."<path>".trust_level="trusted"'`),
  shows a unique marker string in `AGENTS.md` present only in the trusted
  run.
- **Status:** ✅ validated (installed `codex-cli` 0.157.1 via npm and ran
  both cases directly, 2026-09-26). H0 falsified — the untrusted run showed
  no trace of the marker anywhere in the rendered prompt.

### H4: Cursor's confirmed-safe delivery path is static rules, not the sessionStart hook
- **H0 (null):** Cursor's documented `sessionStart` hook
  (`.cursor/hooks.json`, `additional_context` on stdout) is a reliable
  Layer 2 mechanism, safe to install by default.
- **H1 (alternative):** `.cursor/rules/*.mdc` with `alwaysApply: true`
  frontmatter has no open reports of silent failure; the `sessionStart`
  hook does, and runs fire-and-forget (Cursor does not wait for it),
  making it unsafe to rely on without per-version verification this
  environment cannot perform (no registry-distributable Cursor product to
  install — `cursor-agent` on npm was checked and is an unrelated
  third-party package).
- **Acceptance criterion:** a search for current Cursor community/forum
  reports on `sessionStart` + `additional_context` turns up at least one
  open, unresolved report of it not reaching the model.
- **Status:** ✅ validated — found and cited in `cursor/README.md`
  ("sessionStart hook additional_context is never injected into agent's
  initial system context", Cursor community forum, still open as of
  2026-09-26). Consequence: `cursor/install.sh` installs only the rule +
  MCP registration; the hook script exists but is opt-in, documented as
  unverified end-to-end.

### H5: Trae has no hook/session-start mechanism at all (not just unverified)
- **H0 (null):** Trae IDE has some form of session-start hook, as one
  search result claimed ("six Claude-style hook events").
- **H1 (alternative):** That claim traces back to a *feature request* on
  `bytedance/trae-agent` (a separate, unrelated CLI project), not anything
  shipped in the Trae IDE product; Trae's only confirmed delivery surfaces
  are static `.trae/rules/*.md` / `AGENTS.md` and `.trae/mcp.json`.
- **Acceptance criterion:** tracing the "six Claude-style hook events"
  claim to its source either confirms a real Trae IDE hook surface or
  shows it belongs to a different project.
- **Status:** ✅ validated — traced to the `bytedance/trae-agent` feature
  request, confirmed unrelated to Trae IDE; a second, independent source
  (`dyoshikawa/rulesync` issue #2950) explicitly lists "Hooks: No file
  surface found" for Trae. `trae/README.md` documents this as confirmed
  absent, not merely undocumented.

### H6: protocol-header.sh's sync/check/emit are correct once fixed
- **H0 (null):** `sync`, `check`, and `emit` behave correctly on a real
  project protocol (prose before the header, `Phase N` headings present,
  a title in the template's own "name — Scientific Protocol" convention).
- **H1 (alternative):** After four fixes this cycle (header duplication, a
  Python-version-dependent crash, preamble leaking into `emit`, and
  `**Project:**` showing the generic title suffix instead of the real
  project name — the last one found while writing *this file*, see
  Incident (e)), all three commands are correct, idempotent, and don't
  leak content outside the declared header bound.
- **Acceptance criterion:** regression tests for all four bugs, run
  against this repo's own template, pass; `sync` run twice produces
  identical output; `emit`'s output starts with the `START` marker, never
  with unrelated preceding prose; `**Project:**` matches the actual
  project name.
- **Status:** ✅ validated (12/12, `method/test-protocol-header.sh`,
  2026-09-26) — including against this repo's own `SCIENTIFIC_PROTOCOL.md`,
  not only the template fixture.

---

## 2. Phases

### Phase 1 — Discovery
**Goal:** understand current state; compare this method against
`akitaonrails/ai-memory` (a different tool built for cross-agent memory
persistence, not validation/enforcement) at the user's request.
**Status:** complete, 2026-09-26
**Findings:** four real capability gaps identified relative to that tool —
full-text search over a large protocol body, cross-agent delivery beyond
Claude/Devin/Windsurf, a second "service" delivery mode, and adapters for
Cursor/Codex/Trae specifically. Multi-user attribution and multi-machine
sync were found to already be solved via git, not gaps.

### Phase 2 — Pilot
**Goal:** build and validate each gap-closing piece against real evidence,
not assumption — installing the real tool wherever this environment could
reach one.
**Status:** complete, 2026-09-26
**Result:** 5/5 pieces built and independently tested (H1–H5 above), plus
4 real bugs found and fixed in the process (Incident log, below). One
piece (H2, the MCP server) has its wire protocol validated directly but
not a live end-to-end client call — flagged, not hidden.
**Approval to scale:** granted implicitly by continuing to the next
request in the same session (user: "corrija bugs e adapte tudo para
Cursor, Codex, Trae" → "documente tudo o que foi feito no protocolo").

### Phase 3 — Scale
**Goal:** roll the pattern out consistently across every delivery folder,
not just a proof of concept in one.
**Status:** complete, 2026-09-26
**Result:** `method/`, `claude/hooks/`, and `devin/hooks/` all carry the
same fixed `protocol-header.sh` (byte-identical, confirmed by diff);
`codex/`, `cursor/`, and `trae/` each ship `install.sh` + `README.md` +
tests following the same structure as `claude/`/`devin/`; service mode
(`method/service/protocol_mcp_server.py`) is registered identically by
all three new adapters' install scripts. **63/63 tests passing** across 5
independent test files (`method/test-protocol-header.sh` 12,
`method/test-protocol-search.sh` 19,
`method/service/test-protocol-mcp-server.sh` 14,
`cursor/test-cursor-adapter.sh` 9, `trae/test-trae-adapter.sh` 9) — the
12th header test and the last 3 search tests were added by Incidents (e)
and (f) below, both found while writing *this file*, not by auditing the
code that produced it.

### Phase 4 — Monitor
**Goal:** confirm the above holds under real, ongoing use — CI, human
review, and (eventually) a real Cursor/Trae install if one becomes
reachable from this environment.
**Status:** ongoing
**Findings so far:** PR #1 (`bajotto/scientific-method-ai`) open against
`main`, draft, subscribed for CI/review events. No CI configured in this
repository as of this writing (0 check runs on the head commit) — "green"
currently means the local test suites above, not a CI badge.

---

## 3. Incident log

### Incident: 2026-09-26 (a) — PROTOCOL-HEADER duplicated on sync
**What happened:** Running `protocol-header.sh sync` on this repo's own
`method/PROJECT_PROTOCOL_TEMPLATE.md` produced **two** `PROTOCOL-HEADER`
blocks instead of replacing the existing one.
**Root cause:** `sync()` checked `text.startswith(START)` to decide
whether a header already existed. The template (and any real protocol
copied from it) has prose before the header ("Copy this file into the
root of your project..."), so the check was always false there, and the
`else` branch prepended a brand-new header on top of the untouched
original text instead of replacing it in place.
**Fixed by:** match `START..END` anywhere in the text (`START in text and
END in text`), not just at position 0; use a callable `re.sub` replacement
to avoid backslash/backreference interpretation of the generated header
text.
**Lesson:** a boolean gate written as "does the file start with X" is a
narrower claim than "does the file contain X" — worth asking explicitly
which one a check actually needs before writing it, especially when the
file format (here, a template inviting prose before a marker) makes the
narrower case common rather than rare.

### Incident: 2026-09-26 (b) — every subcommand crashed on Python 3.11
**What happened:** `sync`/`check`/`emit`/`hook` all raised `SyntaxError`
on any protocol containing a `### Phase N` heading, in this environment's
Python 3.11.15.
**Root cause:** `phase_index()` built a list entry with a backslash inside
an f-string expression part (`f"{re.sub(r'^###\\s+', ...)}"`), which PEP
701 only makes legal from Python 3.12 onward. The code had evidently been
authored and tested against 3.12+.
**Fixed by:** compute the substitution in a plain variable first, then
interpolate the variable into the f-string.
**Lesson:** "works on my machine" for a stdlib-only script still hides a
language-version dependency; a repo whose own selling point is testing
instead of assuming should pin or at least state its minimum Python
version, and this incident is itself evidence the assumption wasn't
previously checked. (Not yet done: add an explicit minimum-version note to
`method/protocol-header.sh`'s header comment — see next-session checklist.)

### Incident: 2026-09-26 (c) — emit leaked preamble into every hook injection
**What happened:** Generating a Cursor rule file from a real project's
header showed the template's own preamble prose duplicated inside the
"authoritative header" section — the exact content Incident (a)'s fix was
supposed to keep out of the bounded header.
**Root cause:** the `emit` subcommand printed
`text.split(END, 1)[0] + END` — everything from the start of the *file*
through `END`, not the `START..END` span. Harmless when the header sits at
byte 0; leaks whatever precedes it otherwise. `check()`'s "header must end
within first 80 lines" rule had the identical file-start measurement, so a
large preamble could also silently eat into that budget without it being
visible as "header" bloat.
**Fixed by:** extract and measure `text[text.index(START):
text.index(END) + len(END)]` for both `emit` and the 80-line check.
**Lesson:** fixing a bug in one code path (`sync`, for the duplication)
doesn't fix an equivalent assumption baked into a sibling path (`emit`,
`check`) that happens to share the same wrong mental model ("the header is
at the start of the file"). Worth grepping for the same assumption
elsewhere in the file whenever one instance of it is found and fixed —
done here only after noticing the symptom a second time, not by that
grep.

### Incident: 2026-09-26 (d) — install.sh never shipped protocol-search.sh
**What happened:** After adding `protocol-search.sh` and wiring its
commands into the generated header's own advice text, a dry-run install
under a throwaway `HOME` showed the advertised commands would not resolve
on a real machine.
**Root cause:** `claude/install.sh` and `devin/install.sh` each had a
hardcoded loop copying exactly two scripts
(`session-start-protocol-global.sh`, `protocol-header.sh`) into the
installed hooks directory; the loop was never extended when a third
script was added.
**Fixed by:** added an explicit copy step for `protocol-search.sh` in both
install scripts, placing it next to `protocol-header.sh`.
**Lesson:** a hardcoded file list is itself a small piece of state that
can drift from what the rest of the repo assumes exists; caught here only
by actually running the installer end-to-end (a throwaway `HOME`, per
this repo's own "test, don't assume" standard) rather than by reading the
script and reasoning about it.

### Incident: 2026-09-26 (e) — Project: showed the generic suffix, not the project name
**What happened:** Found while writing *this file*: running
`protocol-header.sh sync` on this repo's own freshly-written
`SCIENTIFIC_PROTOCOL.md` (titled "# scientific-method-ai — Scientific
Protocol", per the template's own convention) produced a header whose
`**Project:**` line read "Scientific Protocol" — the generic document type,
not "scientific-method-ai."
**Root cause:** `project_name()` matched the title against
`^#\s+(.+?)(?:\s+—\s+|\s+-\s+)([^\n]+)$` — group 1 is the project name,
group 2 is the generic suffix ("Scientific Protocol") — and returned
`match.group(2)` instead of `match.group(1)`. No existing test asserted on
the `**Project:**` value at all, so this had shipped silently through
Incidents (a)–(d) above without being caught.
**Fixed by:** return `match.group(1)` instead.
**Lesson:** this is the same class of gap Incident (d) named — untested
surface drifting from what the rest of the repo assumes — but found by the
most direct route available: actually using the tool on a real file for
its real purpose (documenting this very session), not by auditing the
code. Writing this protocol *was* Phase 4 monitoring in miniature; the
method caught a defect in its own tooling by being applied, which is the
entire premise of `SCIENTIFIC_METHOD.md`'s "test it and record the
result" anti-pattern row.

### Incident: 2026-09-26 (f) — hypotheses status silently truncated on wrapped prose
**What happened:** Immediately after fixing Incident (e), running
`protocol-search.sh hypotheses` against this very file to sanity-check the
fix showed four of its six real hypotheses (H2, H3, H4, H6) reporting
`Status: (not stated)` — even though every one of them has a `**Status:**`
line with real content.
**Root cause:** two compounding bugs in `cmd_hypotheses()`. First, the
original status-line regex captured only the first physical line of text
after `**Status:**`, so a status written as normal wrapped prose (this
file's own style throughout) lost everything past the first line break. A
first fix added continuation-line joining — but reused the *same* fixed
12-line lookahead window that was meant for locating the Status field
itself, meant for hypotheses whose H0/H1/acceptance-criterion bullets are
short. This file's own bullets are not short: by the time the scan reached
the Status line, the shared window had already run out, leaving zero room
for its continuation lines.
**Fixed by:** decoupled the two searches — first find the hypothesis's
full block boundary (up to the next `###` heading, no fixed cap), then
locate `**Status:**` and join its continuation lines within that same
block boundary, independent of how long the preceding bullets were.
**Lesson:** the first fix attempt was itself under-tested — it was
verified only against the existing fixture in
`test-protocol-search.sh`, whose bullets happen to be one line each, so
the exact failure mode (long bullets pushing Status out of a shared
window) never had a chance to reproduce there. Re-running the fixed tool
against *this file*, not just the existing test fixture, is what surfaced
it. Generalizes directly: a regression test written for the bug you just
found does not, by itself, prove the fix is general — it proves the fix
handles that one fixture. Trying the fix against at least one real,
independently-authored document (this repo's own new file, in this case)
before calling it fixed is what caught the gap the fixture couldn't.

---

## 4. Checklist for the next session

- [ ] Read this file in full, including the incident log, before acting
- [ ] `codex/`, `cursor/`, `trae/`: the MCP path is validated for wire
  correctness (H2) but not for a live client actually calling the
  registered server end-to-end — if a way to drive a real Cursor, Codex
  (with API auth), or Trae session becomes available, run that test and
  update H2's status here rather than assuming it now works
- [ ] `cursor/`, `trae/`: still documentation-only for the product itself
  (no registry-distributable install found) — if either becomes
  installable in this kind of environment, redo the "test, don't assume"
  pass `codex/README.md` and `devin/README.md` already got
- [ ] Revisit whether Cursor's and Codex's `sessionStart`/`additionalContext`
  hooks have been fixed upstream before considering installing either by
  default (currently both are opt-in only, per H4 and the Codex hooks
  section in `codex/README.md`)
- [ ] Check PR #1's CI and review status; this repo has no CI configured
  as of 2026-09-26, so "green" today means the local suites listed in
  Phase 3, not a CI badge — confirm that hasn't silently changed
- [ ] Before claiming any of the above "confirmed," re-run the actual
  command that confirms it — do not rely on this document's memory of the
  result
