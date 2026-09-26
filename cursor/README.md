# Cursor implementation

Same discipline as [`../devin/`](../devin/README.md) and
[`../codex/`](../codex/README.md): every claim below is labeled by whether
it was independently tested. Unlike those two, this repo's test environment
could not install the real Cursor product — `cursor-agent` on npm is an
**unrelated third-party package** (a task-sequencing tool, nothing to do
with Cursor the editor); there is no official Cursor CLI distributed
through a package registry this environment can reach. Everything here is
therefore built from published docs and cross-referenced community reports
(multiple independent sources agree on the schemas below), not from a live
session — the same honesty bar the Devin folder applied to its own
`AGENTS.md` claim before it was tested.

## Confirmed-safe: static project rules

`.cursor/rules/*.mdc` with YAML frontmatter is read automatically. The one
gotcha every source agrees on: it needs the `.mdc` extension and
`alwaysApply: true` in frontmatter — a plain `.md` in that directory, or an
`.mdc` with no frontmatter, is registered but not auto-injected. This is the
same "declare always-on or it's Layer 1" shape as the `.windsurf/rules/*.md`
gotcha `../devin/README.md` found by testing.

[`hooks/sync-cursor-rules.sh`](hooks/sync-cursor-rules.sh) generates
`.cursor/rules/scientific-method.mdc` from the canonical method docs and the
project's current `PROTOCOL-HEADER`, the same derive-from-canonical-source
pattern as `../claude/hooks/sync-windsurf-rules.sh`.

Cursor (and Codex — see `../codex/README.md`) also reads a plain
`AGENTS.md` at the project root as an alternative/complement to
`.cursor/rules/`.

## Confirmed-schema, not confirmed end-to-end: MCP

`.cursor/mcp.json` (global at `~/.cursor/mcp.json`, or project-local at
`<project>/.cursor/mcp.json`) with the schema
`{"mcpServers": {"<name>": {"command", "args", "env"}}}`. This matches the
schema several independent write-ups agree on, and is the same shape Claude
Desktop and several other MCP clients use — but as with Codex, this repo's
environment has no way to drive a live Cursor session to confirm tool calls
actually reach the registered server. What is independently confirmed is
that the server itself speaks correct MCP — see
[`../method/service/test-protocol-mcp-server.sh`](../method/service/test-protocol-mcp-server.sh).

[`hooks/write-cursor-mcp-config.py`](hooks/write-cursor-mcp-config.py)
merges the `scientific-method` entry into whatever `mcp.json` already
exists, idempotently, without touching other servers already registered
there.

## Documented, deliberately not installed: the sessionStart hook

Cursor has a `.cursor/hooks.json` mechanism with a `sessionStart` event
whose stdout can include `{"additional_context": "..."}` — on paper, the
same global Layer 2 mechanism `../claude/` and `../devin/` have, confirmed
working there by an actual test run.

It is not wired up by `install.sh` here for the same reason Codex's
`hooks.json` isn't: there is an open, unresolved Cursor community forum
report of exactly this failure mode — `sessionStart`'s `additional_context`
never reaching the model's initial context on some versions — and the
event is documented to run **fire-and-forget** (the agent loop does not
wait for it), so even a correct response can lose a race with the first
turn. [`hooks/session-start-protocol.sh`](hooks/session-start-protocol.sh)
is provided for reference and does produce a correctly-shaped response
(tested by simulating the documented stdin/stdout shape directly, the same
way `method/service/test-protocol-mcp-server.sh` tests the MCP server
without a live client) — but "produces the right shape" and "Cursor
reliably acts on it" are different claims, and only the first one is
verified here. Wire it into `.cursor/hooks.json` yourself only after
confirming it works on your installed version.

## Setup

```bash
./install.sh /path/to/project
```

Generates the project's `.cursor/rules/scientific-method.mdc` and registers
the `scientific-method` MCP server in that project's `.cursor/mcp.json`.
Re-run any time — both steps are idempotent.

## What this does and does not guarantee

Same distinction as every other implementation here: a rule file being
present is not the same as Cursor's agent acting on it every time. That is
Layer 3 territory — see
[`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).
