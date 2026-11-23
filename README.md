<div align="center">

# Evidence

**A method and tooling to make AI-assisted work verifiable.**
Every claim becomes a testable hypothesis. Every rule lives in a mechanism, not just in a document.

[Install](#install) · [Standalone vs Team](#choose-a-mode) · [Agents](#supported-agents) · [Docs](#documentation) · [Status](#status) · [License](#license)

</div>

---

## Table of contents

- [What it is](#what-it-is)
- [Choose a mode](#choose-a-mode)
- [Install](#install)
  - [Standalone in 3 commands](#standalone-in-3-commands)
  - [Team in 3 stages](#team-in-3-stages)
  - [Let an AI agent install it](#let-an-ai-agent-install-it)
- [Supported agents](#supported-agents)
- [How it works](#how-it-works)
- [Security model](#security-model)
- [Repository layout](#repository-layout)
- [Documentation](#documentation)
- [Tests](#tests)
- [Status](#status)
- [Contributing and public-safe commits](#contributing-and-public-safe-commits)
- [License](#license)

---

## What it is

When an AI agent acts on real systems or real people (sending messages, writing to a database, deploying code), "it works" is not a testable statement. Evidence replaces it with a method:

1. State each assumption as a **hypothesis** with a **measurable acceptance criterion**.
2. Work through fixed phases: **Discovery → Pilot (3–5 real cases) → approval → Scale → Monitor**.
3. Record everything in one running document per project, `EVIDENCE_PROTOCOL.md`: hypotheses, phase results, incidents, next steps.
4. **Inject** a bounded header of that document into the agent's context at session start and on every prompt, so the rules reach the agent without depending on it choosing to read a file.

The method does not prevent errors. It makes them legible: each failure points to the hypothesis that was missing, the phase that skipped validation, or the rule that still lives only in documentation. See [`method/EVIDENCE.md`](method/EVIDENCE.md) and [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md).

## Choose a mode

| | **Standalone** | **Team** (central service) |
|---|---|---|
| Source of truth | `EVIDENCE_PROTOCOL.md` in each repository | PostgreSQL, behind an MCP service |
| Infrastructure | none | Docker host, domain with TLS, Google OAuth client |
| Works offline | yes | live header with cached fallback (marked stale) |
| People | one person or machine | many users, roles `owner` / `editor` / `reader` |
| History | git | immutable revisions, optimistic locking, audit log |
| Secrets | not provided | encrypted vault (AES-256-GCM), shared per user, project or category |
| Admin UI | no | web UI with Google sign-in |
| Setup time | minutes | about an hour, mostly DNS, TLS and Google |
| Guide | [`docs/INSTALL-STANDALONE.md`](docs/INSTALL-STANDALONE.md) | [`docs/INSTALL-TEAM.md`](docs/INSTALL-TEAM.md) |

Start with Standalone if unsure. Joining a Team service later imports your existing `EVIDENCE_PROTOCOL.md` as revision 1.

## Install

Requirements for any path: `bash`, `git`, `python3` 3.11+. Claude Code and Devin installers also need `jq`.

```bash
git clone https://github.com/bajotto/evidence.git ~/evidence
cd ~/evidence
```

### Standalone in 3 commands

```bash
./claude/install.sh                                    # 1. your agent's adapter (see the agent table)
cp method/PROJECT_PROTOCOL_TEMPLATE.md /path/to/project/EVIDENCE_PROTOCOL.md   # 2. the project's protocol
$EDITOR /path/to/project/EVIDENCE_PROTOCOL.md          # 3. fill in project, phase, first hypotheses
```

Then open a **new** agent session in the project. Full steps, every agent and verification: [`docs/INSTALL-STANDALONE.md`](docs/INSTALL-STANDALONE.md).

### Team in 3 stages

| Stage | Who | What | Guide |
|---|---|---|---|
| 1. Deploy | operator, once | `cp .env.example .env`, fill it, `docker compose up -d --build`, add TLS, sign in at `/ui` | [Part A](docs/INSTALL-TEAM.md#part-a-operator) |
| 2. Get a key | each member, once | create an **Evidence secret** (`evk_...`) in the UI, `export EVIDENCE_TOKEN=...` | [B1–B2](docs/INSTALL-TEAM.md#b1-get-your-key) |
| 3. Join | each member, per repository | `python3 evidence_install.py join --target . --agent claude --service-url https://<host>/mcp` | [B3](docs/INSTALL-TEAM.md#b3-join-a-repository) |

```bash
# Stage 3: preview first (no files written, service not contacted), then run again without --dry-run
export EVIDENCE_TOKEN='evk_...'      # never commit or paste this
python3 evidence_install.py join --target . --agent claude \
  --service-url https://evidence.example.com/mcp --dry-run
```

`join` reads the repository's git `origin`. If no project exists for it, the project is created and you become owner; otherwise you are added as editor. The key is referenced by variable name and never written to disk.

### Let an AI agent install it

Point your agent at the runbook. It asks the questions, inspects the target, shows a dry run, waits for approval and verifies the result, for both modes:

```text
Read docs/LLM-INSTALL.md in the Evidence repository and install Evidence for me.
Ask me every question it lists before you change anything.
```

## Supported agents

| Agent | Standalone delivery | Team delivery | Verified |
|---|---|---|---|
| **Claude Code** | global hooks: `SessionStart`, `UserPromptSubmit`, `PostToolUse` (`./claude/install.sh`) | live header via hook + remote MCP (`.mcp.json`) | hooks tested against a real install |
| **Devin CLI** | global hooks + always-on `.windsurf/rules` (`./devin/install.sh`) | same as Claude | tested against a real `devin` install |
| **Codex CLI** | trusted-project `AGENTS.md` + MCP (`./codex/install.sh`) | `.codex/config.toml` + `AGENTS.md` section | `AGENTS.md` trust gate verified; live tool calls not |
| **Cursor** | `.cursor/rules/*.mdc` + MCP (`./cursor/install.sh <project>`) | `.cursor/mcp.json` + rule | schemas from docs; not run against a live Cursor |
| **Trae** | `.trae/rules` + MCP (`./trae/install.sh <project>`) | `.trae/mcp.json` + rule | schemas from docs; no hook mechanism exists |

Delivery means the rules reach the agent's context. It does not guarantee the agent complies; that is enforced in your own code. Per-agent notes, gotchas and caveats are in each adapter's README: [`claude/`](claude/README.md), [`devin/`](devin/README.md), [`codex/`](codex/README.md), [`cursor/`](cursor/README.md), [`trae/`](trae/README.md).

## How it works

```text
Standalone                                   Team
──────────                                   ────
EVIDENCE_PROTOCOL.md  ◄── source of truth    PostgreSQL ◄── source of truth
        │                                          │  revisions · members · audit · vault
  protocol-header.sh                         remote MCP service  +  web UI (/ui)
        │                                          │
  hook / rule injects the                     hook fetches the header with
  bounded PROTOCOL-HEADER                     EVIDENCE_TOKEN (cached, stale-safe)
        │                                          │
        └──────────────► agent context ◄───────────┘
```

- The **PROTOCOL-HEADER** is a small block (current phase, status, gates, indexes) generated from the body. It is what gets injected; the full body stays available through search (`protocol-search.sh hypotheses|incidents|phase|grep`) or the MCP tools.
- In Team mode a hook stays silent after tool calls unless the revision changed. In measured sessions it injected 70–85% fewer tokens than the standalone hooks, and the protocol page shows which members are in sync.
- Writes use an `expected_revision`; a stale write is rejected instead of overwriting another editor.

## Security model

- **Keys.** Each person creates personal `evk_...` keys in the UI. Shown once; only a SHA-256 is stored; up to 10 active; revocable. They authenticate to `/mcp` and `/api/*` with access scope only, never admin.
- **Vault.** AES-256-GCM, key `VAULT_MASTER_KEY` held only by the service, ciphertext bound to the secret's id. Admins manage who can read what but cannot read values. Every read is audited. `evidence_install.py run -- <cmd>` injects permitted secrets as environment variables without printing them.
- **Back up `VAULT_MASTER_KEY` separately from the database.** Losing it makes every secret unrecoverable.
- **Installer.** Never guesses a destination, never starts containers, never writes your key, refuses conflicting files and symlink escapes, preserves unrelated config, supports `--dry-run`.
- **Login.** Google OpenID Connect (code + PKCE, verified email). Only listed admins or users an admin created can enter.

## Repository layout

```text
evidence/
├── README.md                    you are here
├── INSTALLATION_GUIDE.md        index of install docs
├── EVIDENCE_PROTOCOL.md         this project's own protocol (it uses the method)
├── evidence_install.py          join · run · server · project
├── docs/
│   ├── INSTALL-STANDALONE.md    standalone, step by step
│   ├── INSTALL-TEAM.md          operator and member, step by step
│   └── LLM-INSTALL.md           runbook for an AI agent
├── method/                      the method, template, header/search scripts
│   └── service/                 central service: MCP server, UI, vault, Compose
├── claude/ devin/ codex/ cursor/ trae/    per-agent adapters
├── .githooks/ public_safe.py    blocks instance-specific data from being committed
└── test_*.py                    installer and public-safe tests
```

## Documentation

| Document | For |
|---|---|
| [`docs/INSTALL-STANDALONE.md`](docs/INSTALL-STANDALONE.md) | Install without a server |
| [`docs/INSTALL-TEAM.md`](docs/INSTALL-TEAM.md) | Deploy the service, then connect members; reference and troubleshooting |
| [`docs/LLM-INSTALL.md`](docs/LLM-INSTALL.md) | An AI agent installing either mode |
| [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) | Which guide to open |
| [`method/service/README.md`](method/service/README.md) | Service internals, Keycloak overlay, release gates |
| [`method/EVIDENCE.md`](method/EVIDENCE.md) | The method |
| [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md) | Why a rule must live in a mechanism |
| [`method/MULTI_AGENT_MULTI_MACHINE.md`](method/MULTI_AGENT_MULTI_MACHINE.md) | Several agents and machines on one project |
| [`method/PROJECT_PROTOCOL_TEMPLATE.md`](method/PROJECT_PROTOCOL_TEMPLATE.md) | Template for a project's protocol |

## Tests

Standalone and adapter checks:

```bash
bash method/test-protocol-header.sh
bash method/test-protocol-search.sh
bash method/service/test-protocol-mcp-server.sh
bash method/test-central-hooks.sh
bash cursor/test-cursor-adapter.sh
bash trae/test-trae-adapter.sh
```

Installer, UI and service checks (need the packages in `method/service/requirements.txt`):

```bash
python3 -m unittest -v test_evidence_install test_public_safe test_central_hook \
  method.service.test_remote_service method.service.test_markdown method.service.test_ui
```

Database-backed checks run only against a disposable database:

```bash
EVIDENCE_TEST_CONNINFO='host=... dbname=... user=... password=...' \
  python3 -m unittest -v method.service.test_store method.service.test_vault
```

These tests do not assert real-client OAuth, an internet deployment, or restore from backup.

## Status

**Standalone** is the established workflow.

**Team is a pilot.** Implemented and tested: Google sign-in, personal keys, auto-join, revisions with optimistic locking, audit, the vault, the web UI and live hooks. A LAN staging deployment passed a full token-to-MCP end-to-end run. Still open before wider rollout: live verification of every agent against a public HTTPS deployment, backup and restore automation, rate limiting, production monitoring, and a real-project pilot. The optional Keycloak/OAuth overlay is not provisioned automatically and is unverified with live clients.

The code is MIT-licensed and free to use and self-host. That does not cover server, domain, TLS, identity-provider administration or maintenance.

## Contributing and public-safe commits

Only the solution is published, never an instance. Hostnames, IPs, deploy notes, keys and personal notes stay out of git (they are gitignored). Enable the guard once after cloning:

```bash
git config core.hooksPath .githooks
```

`pre-commit`, `commit-msg` and `pre-push` run `public_safe.py`, which rejects private IPs, credential-shaped lines, known token formats and any string listed in the gitignored `.public-safe-deny`, and reports the file and rule but never the matched text. Examples in this repository use `example.com`.

## License

[MIT](LICENSE)
