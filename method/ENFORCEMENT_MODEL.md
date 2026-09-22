# The Enforcement Model: Text, Delivery, and Guarantee Are Three Different Problems

`SCIENTIFIC_METHOD.md` tells you how to validate that a system's output is
correct. This document is about a different, harder problem: how to make
sure a *rule about the system* — "always validate X before scaling," "never
enroll a lead who was already contacted" — actually gets applied, instead of
existing only as a good intention in a file nobody reread at the right
moment.

There are three layers. Each solves a different failure mode of the one
before it.

## Layer 1 — Rule as text

A process document, a `README`, an instruction file. This is necessary —
without it, there is no recorded intent — but it is a weak guarantee. Its
effectiveness depends entirely on someone (a person, or an AI agent
operating the system) choosing to reread it at the right moment, under time
pressure, mid-session.

- **Guarantees:** intent is recorded.
- **Fails when:** no one rereads it in time.

## Layer 2 — Forced context injection

Instead of a link someone may or may not open, a mechanism that loads the
rule automatically, before any action is taken, independent of anyone's
choice. For an AI coding agent this typically means a session-start hook
that injects the relevant documents directly into the agent's context — see
[`../claude/`](../claude/) and [`../devin/`](../devin/) for two independent,
empirically-tested implementations (not just documentation-based guesses —
each was confirmed by running a real prompt and checking the content
actually arrived).

This layer is worth building, and it is verifiable: you can simulate the
startup event and confirm the content actually arrives, across repeated
sessions, without relying on trust. That is a real, testable engineering
guarantee — distinct from hoping someone opens a link.

- **Guarantees:** the rule reaches the agent.
- **Fails when:** the rule is read and not acted on.

That last failure mode is not hypothetical. Delivery and compliance are
different claims. An agent — or a person — can have the complete instruction
present from the first message of a session and still not apply it, because
a large context competes for attention, because the task at hand doesn't
appear to touch that particular rule, or for a reason that isn't always
traceable after the fact. Verifying that a rule was *delivered* is not the
same exercise as verifying it was *followed* — the second requires auditing
actual behavior, not just checking that the injection mechanism fired.

## Layer 3 — Code-level enforcement

The rule as an executable constraint, indifferent to whether anyone read
anything. A test that blocks a change regardless of whether the conventions
document was read. A database constraint that rejects an invalid state
regardless of whether the business rule was remembered. A hard ceiling that
caps scale until a deliberate, auditable action raises it. A circuit breaker
that halts execution automatically once an error rate crosses a threshold.

This is the only layer that does not ask whether the rule reached whoever
is operating the system. It prevents the undesired *outcome* at the point of
execution, not the point of intention — which means it is also the only
layer that is inherently project-specific. It cannot be templated the way
Layers 1 and 2 can; it has to be built into the system it protects.

- **Guarantees:** the outcome, regardless of intent.
- **Fails when:** it hasn't been built yet — i.e., the rule is still only
  living in Layer 1 or Layer 2.

## Layer 2 fails silently by default

A delivery mechanism can be installed, enabled, firing on every session — and
still deliver nothing. Two real defects in this repository's own hook, both
found in production use on 2026-09-22, had that shape:

- The hook resolved the project protocol as `$CWD/SCIENTIFIC_PROTOCOL.md`, with
  no walk up the tree. Sessions that started in a subdirectory of the repo got
  no protocol. The `[ -f ]` test simply failed and the hook moved on.
- `protocol-header.sh` drained stdin unconditionally, so it blocked whenever a
  caller left the pipe open. Under the hook's `timeout`, wrapped in `|| true`,
  a timed-out header sync was indistinguishable from a successful one.

Neither produced an error, a warning or a log line. The agent could not report
the gap, because from inside the session nothing was missing — the protocol had
simply never been mentioned. The failure surfaced only when a human asked
whether the work had been recorded, and the answer was no.

The lesson generalises past these two bugs: **an enforcement mechanism that can
fail open, and says nothing when it does, degrades to Layer 1 without telling
anyone.** It still appears in the settings file, still shows up in code review,
still gets described as "we have a hook for that." When designing Layer 2, make
the negative case loud: if the artifact that was supposed to be injected could
not be found, inject that fact instead of staying quiet, and test the
not-found path as deliberately as the happy path.

## Using this model

Stack all three; don't substitute one for another. For every rule you care
about, ask explicitly which layer it currently lives in:

1. Is it written down anywhere? If not, start there.
2. Is it delivered automatically, or does it depend on someone choosing to
   read a link? If the latter, that's the next gap to close.
3. Is there anything that would stop the bad outcome even if the rule were
   never read at all? If not, the rule is still optional in practice,
   however emphatically it's worded.

The common mistake is investing only in Layer 1 — a more detailed prompt, a
firmer instruction — and treating the problem as solved. Layer 2 is a real,
measurable improvement over that. Treating Layer 2 as sufficient repeats the
same category error one level up: mistaking "the rule was delivered" for
"the rule was followed." Only Layer 3, and an honest audit of what actually
happened, can tell those two apart.
