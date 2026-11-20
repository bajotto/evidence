# Installation Guide

Evidence has two deployment models. **Standalone** keeps the protocol in each project's `EVIDENCE_PROTOCOL.md`. **Central service** stores the authoritative protocol in PostgreSQL and exposes it to agents through authenticated remote MCP. The central path is currently a pilot implementation, not a production service.

## Standalone setup

Choose this for local/offline work without a central database. Keep one `EVIDENCE_PROTOCOL.md` in each project; it is the project's source of truth.

From the Evidence checkout:

```bash
./claude/install.sh   # Claude Code hooks; global for this machine
./devin/install.sh    # Devin CLI hooks; global for this machine
./codex/install.sh    # Codex CLI docs/MCP registration; global for this machine
./cursor/install.sh /absolute/path/to/project
./trae/install.sh /absolute/path/to/project
```

Claude, Devin, and Codex scripts configure machine-level integration; they do not install into the supplied project directory. Cursor and Trae take a project directory. These scripts are retained for standalone/legacy local stdio behavior and do not configure the central remote database.

## Central self-hosted service (pilot only)

The software is MIT-licensed and can be self-hosted without a license fee. Hosting, DNS, TLS/reverse proxy, Google OAuth administration, backups, and operations are not provided for free by this repository. The Compose bundle includes Keycloak 26.6.4, but does not automatically configure a realm, Google OAuth client, identity provider, or client-registration policies. Do not expose it publicly until Google federation is configured and live client tests pass.

### 1. Prepare the service directory

```bash
python3 evidence_install.py server --target /srv/evidence --dry-run
python3 evidence_install.py server --target /srv/evidence
cd /srv/evidence/evidence-server
cp .env.example .env
```

The installer writes the app bundle, two private PostgreSQL services, Keycloak, Compose, and non-secret `.env.example` under `evidence-server/`. It does not start Docker, overwrite differing files, change firewall/DNS, or install host services. Edit `.env` with unique database and Keycloak admin passwords plus public OIDC/MCP URLs and allowed hosts. Keep `.env` out of Git and restrict its file permissions.

Configure DNS/TLS and a reverse proxy for both `OIDC_PUBLIC_URL` and `MCP_PUBLIC_URL`. The local host ports are `127.0.0.1:8081` (Keycloak) and `127.0.0.1:8000` (MCP); neither PostgreSQL service has a host port. Review the rendered Compose config and network/firewall exposure before starting a public endpoint. Automated backup/restore is not implemented yet.

After starting in staging, create the `evidence` Keycloak realm, register a Google OAuth Web client using `{OIDC_PUBLIC_URL}/realms/evidence/broker/google/endpoint` as its redirect URI, configure Google as the realm identity provider, and set the `evidence:access` and restricted `evidence:admin` scopes plus the `evidence-mcp` audience mapper. Configure client-registration/trusted-host policies using [Keycloak's MCP guidance](https://www.keycloak.org/securing-apps/mcp-authz-server); do not leave dynamic registration unrestricted. Keycloak's documented MCP conformance has version-specific gaps, so test actual clients before relying on it.

### 2. Create or import the central project

Connect an authenticated admin MCP client and call `protocol_create_project` with a unique project slug, name, and the reviewed protocol Markdown. This creates revision 1 and makes the caller the owner. For multiuser use, call `protocol_identity` to identify a user, then `protocol_add_member` to grant `owner`, `editor`, or `reader`; membership changes are audited. Never import a local protocol without previewing and approving its content.

### 3. Install project integration in the exact folder

The agent should first read this guide and the adapter, ask the user for the exact existing project directory, agent, service URL, and central project slug, then show a dry run:

```bash
python3 /path/to/evidence/evidence_install.py project \
  --target /absolute/path/to/project \
  --agent claude \
  --service-url https://evidence.example.com/mcp \
  --project-slug project-slug \
  --confirm-project-linked \
  --dry-run
```

Review every proposed path, then rerun without `--dry-run` only after approval. Accepted `--agent` values: `claude`, `devin`, `codex`, `cursor`, `trae`. It writes only project-level files, preserves unrelated config, refuses malformed/colliding config and symlink escapes, validates HTTPS URLs (no embedded credentials/query), and is idempotent. It does not silently trust Codex projects or modify global agent settings.

Every project-mode install requires `--confirm-project-linked`: this is the operator's explicit confirmation that the central slug already exists. If a local `EVIDENCE_PROTOCOL.md` is present, it also confirms that its content was reviewed/imported centrally. The flag does not upload anything. The database remains authoritative; any local Markdown file is only a snapshot. Project-mode installation does not create database records. If it finds a known standalone Evidence rule that could conflict with central state, it stops without writing; review and convert/remove that rule manually. It never deletes existing rules.

For Claude Code or Devin CLI, if a global standalone hook is installed, review and rerun that client's global installer from this checkout to deploy the central-aware hook. The project installer never changes global configuration.

Project-level integration locations:

| Agent | MCP config | Guidance/rule |
|---|---|---|
| Claude Code | `.mcp.json` | `.claude/rules/evidence-central.md` |
| Devin CLI | `.devin/mcp_config.json` | `.windsurf/rules/evidence-central.md` |
| Codex CLI | `.codex/config.toml` | managed section in `AGENTS.md` |
| Cursor | `.cursor/mcp.json` | `.cursor/rules/evidence-central.mdc` |
| Trae | `.trae/mcp.json` | `.trae/rules/evidence-central.md` |

Codex only loads project config for trusted projects; the installer deliberately does not change trust. Remote OAuth behavior and actual tool calls still require end-to-end verification against each installed client version.

## Validation commands

```bash
python3 -m unittest -v test_evidence_install
python3 -m unittest -v method.service.test_remote_service
EVIDENCE_TEST_CONNINFO='host=... dbname=... user=... password=...' \
  python3 -m unittest -v method.service.test_store
bash method/test-protocol-header.sh
bash method/test-protocol-search.sh
bash method/service/test-protocol-mcp-server.sh
bash method/test-central-hooks.sh
bash cursor/test-cursor-adapter.sh
bash trae/test-trae-adapter.sh
```

The PostgreSQL integration test is skipped unless `EVIDENCE_TEST_CONNINFO` points to a disposable isolated test database. Passing unit tests and local database tests do not prove public deployment or live MCP OAuth/client compatibility.
