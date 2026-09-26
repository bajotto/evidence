# Scientific Method for AI-Assisted Work

A reusable structure for validating what an AI agent produces, and for
making the rules about *how* it works actually stick, instead of living
only as good intentions in a document nobody reread at the right moment.

## Structure

```
method/    The method itself — tool-agnostic. Start here.
claude/    Implementation for Claude Code: an inline-rules template
           and a global hook that force-injects the method into every
           session, on every project, on a given machine.
devin/     Implementation for Devin: a global SessionStart hook and
           per-project always-on rules, both confirmed against a real
           Devin CLI session — see devin/README.md for what was tested
           and what (AGENTS.md) is still documentation-only.
```

## Start here

1. Read [`method/SCIENTIFIC_METHOD.md`](method/SCIENTIFIC_METHOD.md) — how
   to validate what your AI-driven system produces, in phases, with
   explicit acceptance criteria. Its `PROTOCOL-HEADER` rule keeps current
   phase, gates, and a body index readable even when protocol history is huge.
2. Read [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md) — why
   a rule being *written down* doesn't mean it will be *followed*, and the
   three layers (text, forced delivery, code enforcement) that close that
   gap, one at a time.
3. Copy [`method/PROJECT_PROTOCOL_TEMPLATE.md`](method/PROJECT_PROTOCOL_TEMPLATE.md)
   into your project as `SCIENTIFIC_PROTOCOL.md` and keep it updated as you
   work. Use [`method/protocol-search.sh`](method/protocol-search.sh) to query
   hypotheses, incidents, and phases without reading the whole file.
4. Set up delivery for your tool: [`claude/`](claude/) or [`devin/`](devin/).
5. Read [`method/MULTI_AGENT_MULTI_MACHINE.md`](method/MULTI_AGENT_MULTI_MACHINE.md)
   if you need the protocol to work across multiple agents, machines, or
   contributors — it already does, mostly via git; that doc says exactly how.

## What this repository does not give you

Layer 3 — code-level enforcement — is intentionally not templated here. A
circuit breaker, a database constraint, a hard scale limit: these only mean
something inside the specific system they protect, and a generic version of
one would be either useless or actively misleading. `ENFORCEMENT_MODEL.md`
explains the principle; building it is project-specific work.

Nothing here guarantees an AI agent follows a rule just because the rule
was delivered to its context. That claim was tested, not assumed: a rule
made mandatory in this way, and confirmed to be technically delivered every
session, was still skipped once in the project this method came from — the
mechanism worked, the text was there, and it still wasn't applied. Forced
delivery closes the "nobody chose to read it" gap. It does not close the
"read it and didn't act on it" gap. Only Layer 3, and an honest audit
against what actually happened, closes that one.

