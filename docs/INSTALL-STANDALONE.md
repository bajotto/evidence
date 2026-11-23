# Install: Standalone

Standalone keeps each project's running history in that project's own `EVIDENCE_PROTOCOL.md`. No server, no database, no network. Hooks and rules read the file; the file is the source of truth.

Use it when you work alone, offline, or want zero infrastructure. If a team must share one protocol and a secrets vault, use [Team](INSTALL-TEAM.md) instead. You can move from Standalone to Team later: `join` imports your existing `EVIDENCE_PROTOCOL.md` as revision 1.

> Automating this with an AI agent? Give it [`LLM-INSTALL.md`](LLM-INSTALL.md) instead; it contains the same steps as a checked runbook.

## Contents

1. [Requirements](#1-requirements)
2. [Get the code](#2-get-the-code)
3. [Install the agent adapter](#3-install-the-agent-adapter)
4. [Create the project protocol](#4-create-the-project-protocol)
5. [Verify](#5-verify)
6. [Update and uninstall](#6-update-and-uninstall)
7. [Troubleshooting](#7-troubleshooting)

## 1. Requirements

| Needed | For | Check |
|---|---|---|
| `bash`, `git` | everything | `bash --version && git --version` |
| `python3` 3.11+ | header/search scripts, MCP stdio server | `python3 --version` |
| `jq` | Claude Code and Devin installers only | `jq --version` |
| The agent itself | the adapter you choose | `claude --version`, `devin --version`, `codex --version`; Cursor and Trae are desktop apps |

Install `jq` if missing: `sudo apt-get install -y jq` (Debian/Ubuntu) or `brew install jq` (macOS).

No Python packages are needed. The standalone MCP server and hooks use only the standard library.

## 2. Get the code

```bash
git clone https://github.com/bajotto/evidence.git ~/evidence
cd ~/evidence
```

Keep this checkout: the installers copy from it and some adapters reference scripts inside it (`method/service/protocol_mcp_server.py`). Re-run an installer after every `git pull`.

## 3. Install the agent adapter

Pick the agent(s) you use. Scope differs: **global** adapters apply to every project on the machine; **project** adapters write into one folder.

| Agent | Command (run from the checkout) | Scope | What it installs |
|---|---|---|---|
| Claude Code | `./claude/install.sh` | global | Copies `EVIDENCE.md` and `ENFORCEMENT_MODEL.md` to `~/.claude/`, hooks to `~/.claude/hooks/`, and merges `SessionStart`, `UserPromptSubmit` and `PostToolUse` into `~/.claude/settings.json` |
| Devin CLI | `./devin/install.sh` | global | Same idea under `~/.devin/` and `~/.devin/hooks.v1.json` |
| Codex CLI | `./codex/install.sh` | global | Docs to `~/.codex/evidence/` and registers the `evidence` MCP server with `codex mcp add` |
| Cursor | `./cursor/install.sh /abs/path/to/project` | project | `.cursor/rules/evidence.mdc` and `.cursor/mcp.json` |
| Trae | `./trae/install.sh /abs/path/to/project` | project | `.trae/rules/evidence.md` and `.trae/mcp.json` |

Notes per agent:

- **Claude Code / Devin.** Existing settings are preserved and the install is idempotent. If a doc in the destination differs from this repository, the script warns and does **not** overwrite it; diff and decide.
- **Devin per-project rules.** For rules specific to one codebase, copy [`../devin/rules/PROJECT_RULE_TEMPLATE.md`](../devin/rules/PROJECT_RULE_TEMPLATE.md) to `<project>/.windsurf/rules/<name>.md`. Keep `trigger: always_on` in its frontmatter, otherwise Devin registers the file but never injects it.
- **Codex.** `AGENTS.md` is only read for a **trusted** project. The installer never marks a project trusted. Copy [`../codex/AGENTS.md.template`](../codex/AGENTS.md.template) to `<project>/AGENTS.md`, then trust the project when Codex asks, or add this to `~/.codex/config.toml`:
  ```toml
  [projects."/absolute/path/to/project"]
  trust_level = "trusted"
  ```
- **Cursor.** Rules need the `.mdc` extension and `alwaysApply: true`; the installer generates this. The optional `sessionStart` hook is intentionally not installed (upstream reports of it silently failing).
- **Trae.** No hook mechanism exists, so static rules are the whole delivery path.
- **Claude `CLAUDE.md` (optional, recommended).** Copy [`../claude/CLAUDE.md.template`](../claude/CLAUDE.md.template) to your project root as `CLAUDE.md` and fill in the placeholders, so the critical rules are inline in the file Claude Code always reads.

Install order does not matter, and you can install several agents on the same project.

## 4. Create the project protocol

In each project, create `EVIDENCE_PROTOCOL.md` at the repository root from the template:

```bash
cp ~/evidence/method/PROJECT_PROTOCOL_TEMPLATE.md /path/to/project/EVIDENCE_PROTOCOL.md
```

Edit the placeholders: project name, current phase, date, status, and your first hypotheses with measurable acceptance criteria. Keep the `PROTOCOL-HEADER:START` / `END` markers; the hooks regenerate the block between them from the body.

For Cursor and Trae, re-run their `install.sh` after the protocol exists so the generated rule contains the real header.

## 5. Verify

**Claude Code.** Open Claude Code in any project and check that the first system message contains `MANDATORY READING injected automatically by the global SessionStart hook`. Then run the hook self-test:

```bash
bash ~/.claude/hooks/test-hooks.sh
```

**Devin CLI.** Run `devin -p "Quote the title of ENFORCEMENT_MODEL.md"` inside a project; a correct answer proves delivery.

**Codex.** `codex mcp get evidence` shows the registration. In a trusted project, `codex debug prompt-input` should contain text from your `AGENTS.md`.

**Cursor / Trae.** Confirm the rule file exists, then ask the agent to state the project's current phase from `EVIDENCE_PROTOCOL.md`.

**Header and search scripts (any agent).** From the project root:

```bash
bash ~/.claude/hooks/protocol-header.sh check EVIDENCE_PROTOCOL.md   # validates the header
~/.claude/hooks/protocol-search.sh hypotheses EVIDENCE_PROTOCOL.md   # lists every H<n> and its status
```

If you only installed Devin, replace `~/.claude` with `~/.devin`.

**Repository self-test** (no install needed):

```bash
bash method/test-protocol-header.sh
bash method/test-protocol-search.sh
bash method/service/test-protocol-mcp-server.sh
bash method/test-central-hooks.sh
bash cursor/test-cursor-adapter.sh
bash trae/test-trae-adapter.sh
```

**What this proves.** Delivery: the rules reach the agent's context. It does not prove compliance, meaning that the agent acts on them. That is the third layer in [`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md) and has to be enforced in your own project's code.

## 6. Update and uninstall

**Update.** `git pull` in the checkout, then re-run each installer you used. They are idempotent.

**Uninstall (Claude Code example).** Remove the three Evidence hook entries from `~/.claude/settings.json` (commands containing `session-start-protocol-global.sh` or `protocol-header.sh hook`), then delete the copied files in `~/.claude/hooks/` and `~/.claude/EVIDENCE.md`, `~/.claude/ENFORCEMENT_MODEL.md`. For Devin, do the same with `~/.devin/hooks.v1.json`. For Codex run `codex mcp remove evidence`. For Cursor and Trae delete the generated rule and the `evidence` entry in `mcp.json`.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: jq is required` | `jq` missing | Install `jq`, re-run |
| `WARNING: ... already exists and differs` | A different copy of a method doc is already installed | `diff` the two files; replace deliberately if the repository version is wanted |
| Hook content is absent in a Claude session | Settings not merged, or session started before install | Check `~/.claude/settings.json` has the three hooks; start a new session |
| Codex ignores `AGENTS.md` | Project not trusted | Trust the project (see above) |
| Devin lists the rule but never injects it | Missing `trigger: always_on` frontmatter | Add it |
| Cursor rule exists but is not applied | Extension is not `.mdc` or `alwaysApply` is missing | Re-run `cursor/install.sh` |
| Header block reports invalid | Markers removed or edited by hand | Restore the `PROTOCOL-HEADER:START/END` markers and run `protocol-header.sh sync` |

Next: [Team install](INSTALL-TEAM.md) when you outgrow a single machine.
