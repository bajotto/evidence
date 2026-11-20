# Evidence for AI-Assisted Work

A reusable method for validating what AI agents produce and making operational rules explicit. The repository supports a file-backed standalone workflow and is developing a self-hosted, multiuser central MCP service.

## Contents

- `method/`: tool-agnostic evidence method, protocol template, search/header utilities, and MCP service.
- `claude/`, `devin/`, `codex/`, `cursor/`, `trae/`: agent-specific standalone adapters and project integration conventions.
- `evidence_install.py`: guided, target-scoped installer for central project integration or a self-hosted service bundle.

## Standalone mode

The established workflow stores each project's running history in that project's `EVIDENCE_PROTOCOL.md`. Hooks or rules read that file; it remains the source of truth. This works locally and offline. See [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md) for the exact per-agent commands and their global vs. project scopes.

## Central service mode

One self-hosted service keeps every project's protocol, its members and a shared secrets vault, so a team uses the same Evidence everywhere. Full operator guide: [`method/service/README.md`](method/service/README.md).

- **Projects and members.** Protocol Markdown, revisions (with optimistic-lock writes), roles, approvals and audit events live in PostgreSQL and are exposed over authenticated Streamable HTTP MCP. A web UI (Google sign-in) manages users, projects and the protocol itself: rendered view, raw, history, edit.
- **Evidence secret.** Each user creates a personal `evk_` key in the UI. It identifies them to the service, so they can join projects and pull secrets. It is shown once and stored only as a hash.
- **Auto-join.** `evidence_install.py join` reads the repo's git remote and calls the service. If the project does not exist it is created (importing a local `EVIDENCE_PROTOCOL.md` if present) and the caller becomes owner. If it exists, the caller is added as a member. The UI also offers a copy-paste prompt that makes an agent do this.
- **Secrets vault.** Credentials, env values and other private data, encrypted with AES-GCM using a key held only by the service. Values are multi-line, copyable after login, grouped by category, and shareable with specific users, projects or categories. Admins manage who can read what but cannot read values. Every read is audited. `evidence_install.py run -- <cmd>` injects permitted secrets as environment variables without printing them.
- **Hooks in central mode.** A project with `.evidence/project.json` gets its header live from the service instead of a local file. It is cached briefly and falls back to the last copy, marked stale, when offline. After tool calls the hook stays silent unless the revision changed. The key is read from `EVIDENCE_TOKEN` and never cached or echoed. In measured sessions this injected 70-85% fewer tokens than the standalone hooks. The service records each read, so the protocol page shows which members are in sync.

Set-up needs a Google OAuth client, a PostgreSQL database and a `VAULT_MASTER_KEY` that you must back up; losing it makes the vault unrecoverable. Still open before wider rollout: backup/restore automation, rate limiting, production monitoring, and live tests for every agent.

The project is MIT-licensed, so the code is free to use and self-host. That does not pay for server, domain, TLS, identity-provider administration, or maintenance.

### Keeping this repository public-safe

Only the solution is published, never an instance. Hostnames, IPs, deploy notes, keys and personal notes files stay out of git: they are gitignored, and `.githooks/` (enable with `git config core.hooksPath .githooks`) runs `public_safe.py` on commits and pushes to reject private IPs, credential-shaped lines, known token formats and any string you list in the gitignored `.public-safe-deny`. Examples use `example.com` and `192.168.50.x`.

## Guided installer

An agent should read this README and [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md), ask the user to select the install mode and exact destination, inspect the target, show a dry run, wait for approval, then verify the result.

```bash
# join (or create) a project with your personal key; EVIDENCE_TOKEN must be set
python3 evidence_install.py join --target /path/to/project --agent claude \
  --service-url https://evidence.example.com/mcp
# run a command with your permitted secrets as env vars
python3 evidence_install.py run --service-url https://evidence.example.com/mcp -- ./deploy.sh
# older flow for a pre-provisioned project, and the self-hosted server bundle
python3 evidence_install.py project --target /path/to/project --agent cursor \
  --service-url https://evidence.example.com/mcp --project-slug project-slug \
  --confirm-project-linked --dry-run
python3 evidence_install.py server --target /srv/evidence --dry-run
```

The installer never guesses the destination, never starts containers, never writes your key to disk, and refuses conflicting files or symlink escapes.

## Tests

Existing standalone checks:

```bash
bash method/test-protocol-header.sh
bash method/test-protocol-search.sh
bash method/service/test-protocol-mcp-server.sh
bash method/test-central-hooks.sh
bash cursor/test-cursor-adapter.sh
bash trae/test-trae-adapter.sh
```

Central pilot tests:

```bash
python3 -m unittest -v test_evidence_install test_public_safe test_central_hook method.service.test_remote_service method.service.test_markdown method.service.test_ui
EVIDENCE_TEST_CONNINFO='host=... dbname=... user=... password=...' python3 -m unittest -v method.service.test_store method.service.test_vault
```

The database test only runs when pointed at a disposable test database. These tests do not assert successful real-client OAuth, internet deployment, or restore from backup.
