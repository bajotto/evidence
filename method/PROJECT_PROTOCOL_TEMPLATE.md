# [PROJECT_NAME] — Scientific Protocol

Copy this file into the root of your project as `SCIENTIFIC_PROTOCOL.md` and
keep it updated as the running record for that project. It is the primary
memory for future sessions — an AI agent (or a teammate) should be able to
read this file alone and understand what has been validated, what failed,
and what is still open.

<!-- PROTOCOL-HEADER:START -->
# PROTOCOL HEADER — READ FIRST

This block is generated from the protocol body and injected at session start and on every prompt. It is the authoritative current-state summary, not a replacement for the full history below.

**Project:** [project name]
**Current phase:** [phase number]
**Last updated (body):** [YYYY-MM-DD]
**Current status (body):** [one line — current phase and what's blocking the next one]

## How to use this protocol
1. Treat every claim as H0 (failure mode) vs H1 (expected result).
2. Require a measurable acceptance criterion and record each case pass/fail.
3. Work in order: Discovery → Pilot (3–5 real cases) → approval → Scale → Monitor.
4. Never scale on a partial pilot; document failures and evidence.
5. Read the full body before acting; this header does not replace history.

## Phase index (details are in the full body)
- Phase 1 — Discovery (see the Phase 1 section below)
- Phase 2 — Pilot (see the Phase 2 section below)
- Phase 3 — Scale (see the Phase 3 section below)
- Phase 4 — Monitor (see the Phase 4 section below)

## Non-negotiable gates
- Phase 1 is read-only discovery; Phase 2 tests 3–5 real cases.
- Phase 2 must be 100% pass and explicitly approved before Phase 3.
- Phase 3 is measured from the real system; Phase 4 monitors outcomes.
- Do not claim production confirmation without running the confirming query.

## Body index
- Testable hypotheses and acceptance criteria — see section 1.
- Phases and phase results — see section 2.
- Incident log and lessons — see section 3.
- Next-session checklist — see section 4.

**Next action:** read the body, verify current phase/status, then state the session start before acting.
<!-- PROTOCOL-HEADER:END -->

**Last updated:** [YYYY-MM-DD]
**Status:** [one line — current phase and what's blocking the next one]

---

## 1. Testable hypotheses

List each hypothesis with an explicit, checkable acceptance criterion —
not a vague goal.

### H1: [short name]
- **H0 (null):** [the failure mode you're worried about]
- **H1 (alternative):** [what you expect to be true]
- **Acceptance criterion:** [specific, measurable — e.g. "100% of X,
  checked against full history, not a sample"]
- **Status:** ⏳ not yet tested / ✅ validated ([N/N], [date]) / ❌ failed
  ([detail])

*(repeat for H2, H3, ...)*

---

## 2. Phases

### Phase 1 — Discovery
**Goal:** understand current state, no execution.
**Status:** [pending / complete, date]
**Findings:** [what you found, in numbers, not impressions]

### Phase 2 — Pilot
**Goal:** validate hypotheses against 3-5 real cases.
**Status:** [pending / complete, date]
**Result:** [N/N pass — list each case, not just the aggregate]
**Approval to scale:** [awaiting / granted, by whom, when]

### Phase 3 — Scale
**Goal:** execute against everything else — only after Phase 2 = 100%.
**Status:** [pending / complete, date]
**Result:** [real numbers from the system, not an estimate]

### Phase 4 — Monitor
**Goal:** confirm outcomes hold under real, ongoing use.
**Status:** [pending / ongoing / complete]

---

## 3. Incident log

One entry per incident. Do not delete old entries — this section is what
prevents the same failure from recurring under a different disguise.

### Incident: [date]
**What happened:** [concrete, specific]
**Root cause:** [the actual mechanism, not just "human error"]
**Fixed by:** [what changed — ideally a Layer 3 fix; see
`ENFORCEMENT_MODEL.md`. A code fix without a documented lesson does not
prevent a differently-shaped repeat.]
**Lesson:** [what this generalizes to, beyond this one incident]

---

## 4. Checklist for the next session

Whoever (or whatever) picks this project up next should confirm, before
acting:

- [ ] Read this file in full, including the incident log
- [ ] Understand which hypotheses are still unvalidated
- [ ] Know where the real enforcement lives (Layer 3 code, not just this
  file) for the rules that matter most
- [ ] Before claiming "confirmed in production," ran the query that
  confirms it
- [ ] If a script already exists for a given check, used or extended it
  instead of writing a new one from scratch
