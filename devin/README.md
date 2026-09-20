# Devin implementation

**Update:** an earlier version of this folder was based only on Devin's
public documentation for `AGENTS.md`, with an explicit note that it hadn't
been tested end-to-end. It has now been tested, against a real Devin CLI
installation (`devin 3000.3.27`) — and the primary mechanism turned out to
be different from what the public docs alone suggested. This version
reflects what was actually confirmed, not what was documented.

## What's actually confirmed

Devin CLI reads project rules from **`.windsurf/rules/*.md`** (Windsurf's
format — confirmed via `devin rules paths` and `devin rules list`), plus a
**hook mechanism** (`~/.devin/hooks.v1.json`) structurally similar to
Claude Code's `SessionStart` hook.

Both were tested for real, not simulated:

- **Global hook** ([`install.sh`](install.sh) +
  [`hooks/session-start-protocol-global.sh`](hooks/session-start-protocol-global.sh)):
  after installing, a real `devin -p "..."` prompt correctly quoted the
  exact title of `ENFORCEMENT_MODEL.md` back — the hook fires and the
  content is delivered into a real session's context, in any project on
  the machine, exactly like the Claude Code implementation in
  [`../claude/`](../claude/).
- **Per-project rules** ([`rules/PROJECT_RULE_TEMPLATE.md`](rules/PROJECT_RULE_TEMPLATE.md)):
  a project-specific rule file, filled in with a project's real
  deploy procedure, was correctly recalled — word for word — by a real
  `devin -p` prompt run from inside that project.

**A gotcha found only by testing, not by reading docs:** a `.windsurf/rules/*.md`
file with no frontmatter is registered by Devin (`devin rules list` shows
it) but defaults to `manual` activation — it exists, but is not injected
automatically. It has to declare `trigger: always_on` in YAML frontmatter
to behave like Layer 2 (forced delivery) instead of Layer 1 (text someone
has to invoke). The template file has this correct; if you write your own
from scratch, don't skip it.

The hook injects the required method documents and the project's bounded
`PROTOCOL-HEADER`. The header contains current phase/status, the phase and body
indexes, and the non-negotiable gates; the full protocol remains available for
history and evidence. It also injects `ENFORCEMENT_CHECKLIST.md` and
`README_SESSIONS.md` when those optional operational documents are present in
the installed Devin document directory. `UserPromptSubmit` re-injects and
validates the header on every prompt, while `PostToolUse` repairs it after
protocol edits.

## Setup

**Global (Layer 2 — the method itself, every project on this machine):**

```bash
./install.sh
```

Installs the hook the same way [`../claude/install.sh`](../claude/install.sh)
does for Claude Code: copies the method docs, installs the hook script,
and merges the hook registration into `~/.devin/hooks.v1.json` (preserving
anything already there, idempotent). If `ENFORCEMENT_CHECKLIST.md` or
`README_SESSIONS.md` are also present in `method/`, they are installed and
injected as optional operational context too.

**Per-project (critical rules specific to one codebase):**

Copy [`rules/PROJECT_RULE_TEMPLATE.md`](rules/PROJECT_RULE_TEMPLATE.md) to
`<project>/.windsurf/rules/<name>.md`, fill in the placeholders, and keep
the `trigger: always_on` frontmatter.

## What this does and does not guarantee

Same distinction as the Claude Code implementation, and worth repeating
because it's the point of this whole repository: this guarantees
**delivery**. A real, tested prompt confirms the content reaches Devin's
context, automatically, every session. It does not guarantee
**compliance** — that Devin will act on what it received. That is Layer 3
territory, see [`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md),
and it has to be built into your own project's code, not into this hook or
rule file.

## `AGENTS.md` (secondary, still unverified)

[`AGENTS.md.template`](AGENTS.md.template) is kept for reference — Devin's
public documentation states it reads `AGENTS.md` at the start of a task,
which may be complementary to the always-on rules mechanism above (e.g.
for task-scoped context rather than persistent rules). This specific claim
has **not** been independently tested the way the two mechanisms above
were. Validate it yourself before relying on it, the same way the always-on
mechanism was validated here instead of assumed.
