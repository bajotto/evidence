# The Scientific Method for AI-Assisted Work

Applies to any task where an AI agent generates output that will act on real
systems or real people: sending messages, writing to a database, deploying
code, modifying production data. The method does not prevent errors — no
process does. It makes errors legible: each failure points to exactly which
hypothesis was missing, which phase skipped validation, or which rule still
lives only in documentation instead of in a mechanism (see
[`ENFORCEMENT_MODEL.md`](ENFORCEMENT_MODEL.md) for that distinction).

## The core idea

Treat every claim about the system as a hypothesis, not a fact. "It works" is
not a testable proposition — there is no way to check it against anything.
"Zero percent of outputs contain an unresolved placeholder, measured against
100% of history, not a sample" is testable. Restate assumptions this way
before acting on them.

## Information-preservation rule: inject the HEADER, preserve the history

A protocol can exceed an agent context cap without losing its most important
current state. Every `SCIENTIFIC_PROTOCOL.md` must therefore begin with a
small, readable `PROTOCOL-HEADER` generated from the body. The header is the
first context delivered at session start and on every prompt; the full body
remains the source of history, evidence, incidents, and detailed phase notes.

The header must accurately contain, at minimum:

- current phase, current status, and body update date;
- a short H0/H1 and measurable-acceptance-criteria reminder;
- an ordered phase index with body line references or an explicit search
  pointer when the history is too large to list completely;
- the non-negotiable pilot/approval/scale gates; and
- an index pointing to hypotheses, phases, incidents, and the next-session
  checklist in the full body.

The header is not hand-maintained. A checker must reject missing, duplicated,
oversized, or incomplete headers. Session and prompt hooks must regenerate and
validate it after protocol edits, including edits made through opaque shell
commands. A passing header proves accurate delivery of current state; it does
not prove that the agent followed the method.

## The method

### 1. State a falsifiable hypothesis

```
H0 (null):        The claim you're worried might be true
H1 (alternative):  What you actually expect to be true

Wrong:   "The system works."
Right:   H0: The system sends messages with unresolved placeholders.
         H1: The system sends clean messages (100% valid).
```

### 2. Define explicit, measurable acceptance criteria

```
Wrong:   "Messages should look good."
Right:   - 100% of messages contain no unresolved placeholder
         - Zero occurrences of a broken reply-to address
         - 100% contain the correct target URL
         - No message is sent twice to the same recipient
```

### 3. Execute in small, approved phases

```
Phase 1 — Discovery   Read-only. Document current state and assumptions.
Phase 2 — Pilot       3-5 real cases, executed and reviewed by hand.
Phase 3 — Scale       Everything else — only if Phase 2 passed 100%.
Phase 4 — Monitor     Collect real outcomes; update the hypotheses.
```

Do not skip a phase. A pilot that validates *content* does not validate
*behavior under concurrency or volume* — see the note on that gap in
[`ENFORCEMENT_MODEL.md`](ENFORCEMENT_MODEL.md).

### 4. Require explicit approval between phases

```
Phase 1 complete → approval required → Phase 2
Phase 2 complete (100% pass) → approval required → Phase 3
Phase 3 complete → analysis and documentation
```

If Phase 2 does not pass 100%, return to Phase 1. Do not proceed on a
partial pass.

### 5. Document every phase — including failures

For each phase, record: what was tested, the acceptance criteria, the
result (pass/fail per item, not just an aggregate), and what happened when
something failed. A result that isn't documented isn't reproducible, and a
failure that isn't documented will recur under a different disguise.
Use [`PROJECT_PROTOCOL_TEMPLATE.md`](PROJECT_PROTOCOL_TEMPLATE.md) as the
running record for a given project.

## Anti-patterns

| Instead of this | Do this |
|---|---|
| Scaling before validating 3-5 cases | Validate 3-5, confirm 100%, then scale |
| Acting without approval between phases | Ask for explicit approval at each gate |
| Ignoring errors "because it mostly works" | Document every error, including near-misses |
| Assuming a component works | Test it and record the result |
| Treating a passed pilot as a finished validation | Ask which failure classes the pilot didn't cover |
| Writing "confirmed in production" from memory | Run the query that confirms it, first |

## What this does not cover

This method validates *what the system produces* and *whether the plan was
followed*. It does not, by itself, guarantee that the plan will be followed —
that a rule written here will actually be read and applied in a given
session. That is a separate problem, addressed in
[`ENFORCEMENT_MODEL.md`](ENFORCEMENT_MODEL.md).
