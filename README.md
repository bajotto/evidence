# Scientific Method for AI-Assisted Work

A reusable structure for validating what an AI agent produces, and for
making the rules about *how* it works actually stick, instead of living
only as good intentions in a document nobody reread at the right moment.

## Structure

```
method/    The method itself — tool-agnostic. Start here.
           method/service/ is standalone mode's counterpart: a persistent
           MCP server any MCP-capable agent can call instead of re-running
           a hook every session — see "Standalone vs. service mode" below.
claude/    Implementation for Claude Code: an inline-rules template
           and a global hook that force-injects the method into every
           session, on every project, on a given machine.
devin/     Implementation for Devin: a global SessionStart hook and
           per-project always-on rules, both confirmed against a real
           Devin CLI session — see devin/README.md for what was tested
           and what (AGENTS.md) is still documentation-only.
codex/     Implementation for OpenAI Codex CLI: AGENTS.md (confirmed —
           but only for a project marked "trusted", a real finding, not
           documented upstream) plus MCP registration.
cursor/    Implementation for Cursor: static .cursor/rules/*.mdc (confirmed
           format) plus MCP registration. A sessionStart hook exists but
           is not installed — open upstream reports of it silently not
           reaching the model, see cursor/README.md.
trae/      Implementation for Trae IDE: static .trae/rules/*.md (confirmed
           format) plus MCP registration. No hook mechanism exists at all
           for Trae — confirmed absent, not just unverified.
```

Every one of these implementation folders states, explicitly, what was
independently tested against a real install of that tool versus what is
carried over from documentation/community reports only — this repo's own
`ENFORCEMENT_MODEL.md` exists because "documented" and "true in practice"
are different claims, and that discipline applies to this repo's own claims
about other tools too.

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
4. Set up delivery for your tool: [`claude/`](claude/), [`devin/`](devin/),
   [`codex/`](codex/), [`cursor/`](cursor/), or [`trae/`](trae/).
5. Read [`method/MULTI_AGENT_MULTI_MACHINE.md`](method/MULTI_AGENT_MULTI_MACHINE.md)
   if you need the protocol to work across multiple agents, machines, or
   contributors — it already does, mostly via git; that doc says exactly how.

## Standalone vs. service mode

Every tool folder above sets up **standalone mode**: no daemon, the tool's
own hook or static-rule mechanism re-reads `SCIENTIFIC_PROTOCOL.md` (via
`protocol-header.sh` / `protocol-search.sh`) each session. Zero dependencies,
works offline, and is what `claude/` and `devin/` have done since this
repo's first commit.

**Service mode** is the alternative, not a replacement:
[`method/service/protocol_mcp_server.py`](method/service/protocol_mcp_server.py)
is one persistent process, speaking plain MCP (JSON-RPC 2.0 over stdio — no
third-party dependency, no daemon framework), that any MCP-capable agent
can call directly instead of shelling out per session. Cursor, Codex CLI,
and Trae IDE all support MCP as a client (confirmed — see each tool's own
README for exactly how); `codex/install.sh`, `cursor/install.sh`, and
`trae/install.sh` all register it. Run both modes side by side; they read
the same `SCIENTIFIC_PROTOCOL.md` and never conflict.

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

