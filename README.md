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

## Quick start (3 steps)

**For humans setting up a project:**
1. Read [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) — choose standalone or service mode, then run one `install.sh` command
2. Copy [`method/PROJECT_PROTOCOL_TEMPLATE.md`](method/PROJECT_PROTOCOL_TEMPLATE.md) to your project as `SCIENTIFIC_PROTOCOL.md`
3. Start using [`method/SCIENTIFIC_METHOD.md`](method/SCIENTIFIC_METHOD.md) to write your protocol

**For agents (Claude, Devin, Cursor, etc.):**
1. Follow [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) steps for your tool
2. Ask the human which mode they prefer (standalone = zero daemon, service = shared server)
3. Run the `install.sh` for their tool, copy the template, point them to the method docs

## Full documentation

- [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) — **start here** — how to install standalone or service mode
- [`method/SCIENTIFIC_METHOD.md`](method/SCIENTIFIC_METHOD.md) — how to write and maintain your protocol
- [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md) — why delivery mode matters (3 layers: text, forced delivery, code enforcement)
- [`method/MULTI_AGENT_MULTI_MACHINE.md`](method/MULTI_AGENT_MULTI_MACHINE.md) — cross-agent, cross-machine, multi-user setup (already solved by git)
- `{tool}/README.md` (e.g., [`cursor/README.md`](cursor/README.md)) — what's confirmed vs. documentation-only for each tool
- [`method/protocol-search.sh`](method/protocol-search.sh) — query your protocol without reading the whole body

## Two delivery modes (choose one, or run both)

**Standalone** (recommended for most): Hook or static rule runs each session, re-reads the protocol. Zero daemon. Works offline. Default for all agents.

**Service** (optional, via MCP): One persistent process answers protocol queries. Slightly faster, ideal for multiple agents on one machine. Cursor, Codex, and Trae can use this instead of hooks.

**Both run on the same `SCIENTIFIC_PROTOCOL.md` and never conflict.** See [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) for complete setup instructions and trade-offs.

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

