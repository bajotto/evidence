# Trae IDE implementation

Same discipline as the other adapters: labeled by what's actually
confirmed. This repo's test environment could not install the real Trae
IDE (it is a desktop application, not distributed through a package
registry this environment can reach), so everything here is built from
`docs.trae.ai` and cross-referenced third-party write-ups that agree with
each other — not from a live session. Where sources disagreed or were
silent, that's stated rather than guessed.

## Confirmed: static project rules

`.trae/rules/*.md` — plain Markdown files under the project root, read
**recursively up to three directory levels** (a subfolder's own
`.trae/rules/` scopes to files under that subfolder). Global rules, applied
to every project, live in `~/.trae/user_rules`. `alwaysApply` in YAML
frontmatter is confirmed; other fields some tools support (`globs`,
`description`) are not confirmed for Trae specifically — this repo's
generated rule only relies on `alwaysApply`.

Trae also reads a plain `AGENTS.md` at the project root, including nested
per-module versions, with the same activation logic as `.trae/rules/` — the
same file Codex and (as an alternative) Cursor read.

[`hooks/sync-trae-rules.sh`](hooks/sync-trae-rules.sh) generates
`.trae/rules/scientific-method.md` from the canonical method docs and the
project's current `PROTOCOL-HEADER` — same derive-from-canonical-source
pattern as the Cursor and Windsurf adapters.

## Confirmed-schema, not confirmed end-to-end: MCP

`.trae/mcp.json`, project-scoped only (no documented global MCP surface),
same `{"mcpServers": {"<name>": {"command", "args", "env"}}}` shape as
Cursor's. [`hooks/write-trae-mcp-config.py`](hooks/write-trae-mcp-config.py)
merges the `scientific-method` entry in, idempotently. As with the other
adapters, the server's own MCP correctness is independently tested (see
[`../method/service/test-protocol-mcp-server.sh`](../method/service/test-protocol-mcp-server.sh));
Trae actually calling it end-to-end is not, for the same environment reason.

## Confirmed absent: no hook / session-start mechanism

Unlike Cursor and Codex — both of which have a session-start-style hook,
just with open reliability bugs neither is wired up here — Trae has **no
documented hook or lifecycle-event file surface at all**. (An early search
during this work surfaced a claim that Trae supports "six Claude-style
hook events," which turned out to trace back to `trae-agent`, a separate
ByteDance CLI project, and a still-open *feature request* there, not
anything shipped in the Trae IDE product. Chasing that down and ruling it
out is exactly the kind of claim this repo insists on verifying rather than
repeating.) Static rules are therefore not a fallback for Trae — they are
the entire standalone-mode delivery mechanism.

## Setup

```bash
./install.sh /path/to/project
```

Generates `.trae/rules/scientific-method.md` and registers the
`scientific-method` MCP server in that project's `.trae/mcp.json`. Re-run
any time — both steps are idempotent.

## What this does and does not guarantee

Same distinction as every other implementation here: a rule file being
present is not the same as Trae's agent acting on it every time — see
[`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).
