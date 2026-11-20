# Claude Code implementation

Two independent pieces. Use both — they cover different layers of
[`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).

## 1. Inline critical rules in `CLAUDE.md` (Layer 1)

Copy [`CLAUDE.md.template`](CLAUDE.md.template) to the root of your project
as `CLAUDE.md` and fill in the placeholders. `CLAUDE.md` is read
automatically by Claude Code at the start of every session in that project
— but only the rules that are actually *in* it benefit from that. A rule
that's one click away, in a linked file, is still Layer 1 text that depends
on someone opening the link.

## 2. Global SessionStart hook (Layer 2)

[`hooks/session-start-protocol-global.sh`](hooks/session-start-protocol-global.sh)
is a hook that fires on every session start, in every project, on this
machine — and injects the method documents directly into the agent's
context before it takes any action. It also auto-detects and injects a
project's own `EVIDENCE_PROTOCOL.md` if one exists at the project root,
with no per-project setup.

The hook injects only the bounded `PROTOCOL-HEADER` for the project protocol,
not an arbitrary head slice of its history. The header carries current phase,
status, phase/body indexes, and the approval gates; the full protocol remains
available for detailed evidence.

Install it:

```bash
./install.sh
```

This copies the method docs to `~/.claude/`, installs the hook script to
`~/.claude/hooks/`, and merges the hook registration into
`~/.claude/settings.json` — it preserves any existing settings and is safe
to run more than once (it won't duplicate the entry).

To confirm it worked, open Claude Code in any project on the machine — the
first system message should include the hook's injected content.

### What this does and does not guarantee

The hook guarantees **delivery**: the rules reach the agent's context,
every session, without depending on a choice to read a link. It was built
specifically to close that gap, and it's worth verifying that gap is
actually closed — simulate the hook's exact input and confirm the expected
content comes back, rather than assuming the configuration is correct.

It does **not** guarantee **compliance**. An agent can have the full rule
present from the first message of a session and still not act on it. That
is a separate, harder problem — Layer 3 in
[`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md), and it
has to be solved in your own project's code, not in this hook.

## Central service integration (pilot)

For central PostgreSQL-backed protocols, use the repository-root installer described in `../INSTALLATION_GUIDE.md`:

```bash
python3 evidence_install.py project --target /path/to/project --agent claude \
  --service-url https://your-service.example/mcp --project-slug your-project \
  --confirm-project-linked --dry-run
```

Review the generated `.mcp.json` and `.claude/rules/evidence-central.md` before rerunning without `--dry-run`. If the machine's global standalone hook is installed, rerun `./claude/install.sh` to install its central-aware version; it skips local protocol injection for central projects and adds a pointer to MCP. The hook does not fetch live state itself. Remote OAuth behavior has not yet been verified against a live Claude Code install.
