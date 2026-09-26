# Codex CLI implementation

Same discipline as [`../devin/`](../devin/README.md): what's below is marked
by what was actually run against a real `codex-cli 0.157.1` install (via
`npm install -g @openai/codex`), not inferred from documentation alone. One
finding below only showed up by testing, exactly like the Devin folder's own
`.windsurf/rules/*.md` gotcha.

## What's actually confirmed

**`AGENTS.md` is read and injected into the model-visible prompt —
but only for a project marked `trusted`.** Verified with
`codex debug prompt-input`, which renders the exact prompt Codex would send:

- A fresh project, no trust configured: an `AGENTS.md` with a unique marker
  string was **not** present anywhere in the rendered prompt. No error, no
  warning — the file is simply not there, the same silent-gap shape this
  repo's `ENFORCEMENT_MODEL.md` warns about for any Layer 2 mechanism.
- The same project with
  `-c 'projects."<path>".trust_level="trusted"'`: the marker **was** present.

This is not documented clearly in Codex's own public docs, which describe
`AGENTS.md` without mentioning the trust gate. Do not assume `AGENTS.md`
alone is enough — trust it explicitly per project (`install.sh` explains
why that's a manual, per-project decision, not something to automate).

Discovery rule (read from `codex-rs/core/src/agents_md.rs`): Codex walks
**upward** from the working directory to find a project root (nearest
`.git`), then concatenates every `AGENTS.md` from that root **down to**
the working directory, `AGENTS.override.md` taking precedence over
`AGENTS.md` at the same level. Content is truncated at `project_doc_max_bytes`
(default 32KB, configurable in `config.toml`).

**MCP server registration works exactly as documented.**
`codex mcp add scientific-method -- python3 .../protocol_mcp_server.py`
writes a `[mcp_servers.scientific-method]` table to `~/.codex/config.toml`
with the exact `command`/`args` given, confirmed idempotent (re-running
updates the entry, does not duplicate it). `install.sh` uses this instead
of hand-writing TOML.

**Not independently confirmed end-to-end:** that Codex's live runtime
actually spawns the registered server and calls its tools — that requires
API auth and a real turn, which this environment could not do. What *is*
independently confirmed is that `protocol_mcp_server.py` itself speaks
correct MCP (JSON-RPC 2.0, newline-delimited stdio, `initialize` /
`tools/list` / `tools/call`) — see
[`../method/service/test-protocol-mcp-server.sh`](../method/service/test-protocol-mcp-server.sh).
If registration succeeds but tool calls don't, the server side is the
already-tested part; look at the client side first.

## What's documented but deliberately not installed here

Codex has a `hooks.json` mechanism (`SessionStart`, `UserPromptSubmit`,
`PreToolUse`, etc. — the same event names Claude Code uses, and the same
`hookSpecificOutput.additionalContext` shape for injecting context). On
paper this would give Codex the same global, every-project Layer 2 hook
that [`../claude/`](../claude/) and [`../devin/`](../devin/) have.

It is not wired up here because, at the time of writing, multiple upstream
issues report exactly the failure mode `ENFORCEMENT_MODEL.md` warns about —
`SessionStart` hooks whose `additionalContext` is silently rejected, or that
don't fire at all when a session auto-resumes a previous thread. Shipping an
adapter for a mechanism with open reports of failing silently, without a way
to verify it in this environment, would be worse than not shipping one — a
false claim of Layer 2 delivery is worse than an honest Layer 1. If you
confirm it works on your installed version, a `codex/hooks/` adapter mirroring
`claude/hooks/session-start-protocol-global.sh` is a straightforward port —
the payload shape is close enough to Claude Code's that most of the
`jq`-free Python logic in `protocol-header.sh` can be reused as-is.

## Setup

```bash
./install.sh
```

Copies the canonical docs to `~/.codex/scientific-method/` for reference,
and registers the `scientific-method` MCP server globally if `codex` is on
`PATH`. Then, per project:

1. Copy [`AGENTS.md.template`](AGENTS.md.template) to `<project>/AGENTS.md`
   and fill it in.
2. Trust the project yourself — either interactively (`codex` will ask the
   first time you run it there) or by adding the block `install.sh` prints
   to `~/.codex/config.toml`. This script does not do it for you; see the
   security reasoning in `install.sh`'s header comment.

## What this does and does not guarantee

Same distinction as every other implementation in this repo: confirming
`AGENTS.md` is delivered under a trusted project is not the same as
confirming Codex acts on what it read. That is Layer 3 territory — see
[`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).
