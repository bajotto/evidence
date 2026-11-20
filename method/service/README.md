# Central Evidence service — pilot implementation

This mode stores the authoritative Markdown protocol and its revisions in PostgreSQL. Clients connect to the remote MCP endpoint over HTTPS/Streamable HTTP; each tool call is authenticated and authorized by project membership. A local `EVIDENCE_PROTOCOL.md` is not read by the central service.

This implementation is a **development pilot, not production-ready**. The Compose bundle includes Keycloak 26.6.4 as the OAuth authorization server, but does not provision a realm, Google credentials/identity provider, scope policies, or client registration policies. Live Claude Code, Devin CLI, Codex, Cursor, and Trae OAuth flows have not been verified, and there is no backup/restore automation. Do not expose it to the public internet or import real project protocols until these gaps are closed and the 3–5 protocol pilot is approved.

## Components

- `remote_mcp_server.py`: Streamable HTTP MCP resource server.
- `store.py` and `schema.sql`: PostgreSQL project records, memberships, current protocol, immutable revisions, approvals, and audit events.
- `oidc.py`: validates RS256 bearer tokens against the configured Keycloak issuer/JWKS, audience, expiry, subject, and scopes.
- `compose.yaml`: Evidence PostgreSQL, Keycloak with a separate PostgreSQL database, and the MCP app. Neither database is host-published; Keycloak and MCP bind to host loopback for separate HTTPS reverse proxies.
- `evidence_install.py`: safe project-configuration and service-bundle installer modes.

Keycloak is the MCP OAuth authorization server and can federate users to Google. Google OIDC alone is not the MCP authorization server. The operator configures Google in Keycloak, grants the appropriate scopes, and sets client-registration policies. The service validates access tokens; it does not issue them or automatically configure the Google application/realm.

## Prepare the self-host bundle

From the repository root:

```bash
python3 evidence_install.py server --target /srv/evidence --dry-run
python3 evidence_install.py server --target /srv/evidence
cd /srv/evidence/evidence-server
cp .env.example .env
```

Edit `.env` with strong unique passwords, the public Keycloak URL (`OIDC_PUBLIC_URL`), the public MCP URL, and allowed host/origin values. Restrict `.env` permissions and do not commit it. The installer only lays down files; it does not start Docker, alter firewall/DNS, install a reverse proxy, or deploy to the internet.

Configure DNS/TLS and a reverse proxy for both URLs. Register this Google OAuth redirect URI in Google Cloud:

```text
{OIDC_PUBLIC_URL}/realms/evidence/broker/google/endpoint
```

Then start the local stack in staging and use the Keycloak admin console to create the `evidence` realm, configure the Google identity provider, and configure the MCP client-registration policy. Create/assign `evidence:access` to normal users and `evidence:admin` only to service administrators. Map the `evidence-mcp` audience into access tokens. Follow Keycloak's [MCP authorization guide](https://www.keycloak.org/securing-apps/mcp-authz-server), especially its trusted-host and dynamic client-registration policy guidance; do not allow unrestricted public registration.

Keycloak's MCP conformance varies by specification revision; the current docs list gaps around Resource Indicators in newer revisions. Live client compatibility is a release gate. If a client cannot complete OAuth against this Keycloak version, stop and evaluate an authorization server that supports that client's required revision before scale.

The host ports are `127.0.0.1:8081` for Keycloak and `127.0.0.1:8000` for MCP; PostgreSQL has no host ports. Review rendered Compose config and firewall rules before exposing either HTTPS endpoint. Backup/restore automation is not implemented yet.

## Create/import a project

An authenticated service administrator with `evidence:admin` calls the `protocol_create_project` MCP tool with a unique slug, project name, and reviewed initial Markdown. This creates revision 1 and an owner membership. The administrator can obtain their OIDC subject with `protocol_identity`; use `protocol_add_member` to grant `owner`, `editor`, or `reader` roles. `protocol_members_list` and `protocol_audit_history` expose membership and audit history. Removing the last owner is rejected.

For an existing local `EVIDENCE_PROTOCOL.md`, inspect and approve the content before importing it. Keep the local file as a snapshot only; database content is authoritative. Then configure the project folder:

```bash
python3 evidence_install.py project \
  --target /path/to/project \
  --agent claude \
  --service-url https://evidence.example.com/mcp \
  --project-slug project-slug \
  --confirm-project-linked \
  --dry-run
```

Review the listed paths, then repeat without `--dry-run`. The installer merges only the selected project's agent config and instructions, rejects incompatible name collisions, rejects symlink escapes, and does not modify global client settings. `--confirm-project-linked` is required for every project install to confirm the central slug exists; if a local protocol exists, it also confirms that the content was reviewed/imported. The flag does not perform the import.

## Central-aware global hooks

The Claude Code and Devin global hooks detect `.evidence/project.json`. For central projects, they inject a pointer to the live MCP tools and skip any local `EVIDENCE_PROTOCOL.md` snapshot; for standalone projects, they keep the existing file-backed behavior. Updating hook files in this checkout does not alter a user's home directory. If the global standalone hooks are already installed, rerun the Claude/Devin global installer after reviewing its settings merge to deploy the central-aware scripts. Project-mode installation does not modify global configuration implicitly.

The hook injects a pointer, not the database contents. The agent still must call MCP for current state; tool availability does not force the model to call it.

## Tool behavior and data integrity

- `protocol_get`, `protocol_header`, and `protocol_search` read the current database revision.
- `protocol_update` requires an `expected_revision`, checks project role, normalizes the generated header, and creates the next revision and audit record in one transaction. Stale writes conflict instead of overwriting another editor.
- `protocol_approve_phase` records an approval against an exact revision.
- `protocol_identity`, `protocol_projects_list`, `protocol_add_member`, `protocol_remove_member`, `protocol_members_list`, and `protocol_audit_history` support identity, access, and audit workflows.
- Header/search reuse the existing scripts against a temporary copy. No local project path is accepted by the remote tools.

## Remaining release gates

Before production use, configure and test Google sign-in, Keycloak client registration/scope policies, and end-to-end OAuth/tool calls for all five agents; test rate limiting, encrypted backup/restore, and operational monitoring; and run the approved 3–5 real-project pilot with 100% pass. Hosting, domain, reverse proxy/TLS, Google OAuth administration, backups, and maintenance remain the self-hosting operator's responsibility. The code is MIT-licensed; this does not promise zero infrastructure cost.

## Users, vault, admin UI, and auto-join

- **Two different kinds of secret.** An **Evidence secret** is a person's own key (`evk_...`): it lets them and their AI
  agents join projects and pull what is shared with them. Everyone generates theirs in the web UI after logging in
  (**Evidence secret** page): it is shown once, only its SHA-256 is stored, up to 10 can be active, and it can be revoked
  at any time. The **secrets** in the vault are the private information itself (like a Cloudflare token, a database login,
  an API key). Evidence secrets only open the door; they are never stored in or shared through the vault. Tokens
  authenticate to `/mcp` and `/api/*` with `evidence:access` only, never admin.
- **Auto-join.** In any repository: `EVIDENCE_TOKEN=evk_… python3 evidence_install.py join --target . --agent claude
  --service-url https://host/mcp`. The repo's git origin becomes the join key. If no project has that key it is created
  and the caller becomes owner; otherwise the caller is added as `editor`. Re-running is idempotent and never downgrades.
  The generated MCP config references `${EVIDENCE_TOKEN}` by name; the token is never written to disk.
- **Vault: secrets that are shared across projects and people.** A secret is an independent item (AES-256-GCM, key
  `VAULT_MASTER_KEY`, bound to the secret's id), owned by whoever created it. The owner shares it with any number of
  projects and/or named users. A person can read it if they own it, if it was shared with them directly, or if they are
  in a project it is shared with and either own that project or were granted the secret's category there. Only the
  owner (or an admin) rotates, reshares or deletes it. The `evidence:admin` scope can manage but cannot read values
  unless it also qualifies through sharing. Every read is audited. Agents should use
  `EVIDENCE_TOKEN=... python3 evidence_install.py run --target . -- <command>`, which injects the secrets shared with the
  project as environment variables without printing them. **Back up `VAULT_MASTER_KEY` separately; losing it loses every secret.**
- **Web UI** (`/ui`, enabled when `UI_SESSION_SECRET`, `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set).
  Login is Google OpenID Connect (code + PKCE, verified email required). A Google account may enter only if an admin
  created a user with that email, or it is listed in `ADMIN_EMAILS`. Every user gets **Secrets** (what they own or
  what was shared with them, with **Reveal** and **Copy to clipboard**, plus a **New secret** page with a multi-line value box, description and sharing pickers, and a **Manage** page to share
  or rotate their own) and **Evidence secret**. Values are not in the page HTML; they are fetched on
  click (CSRF-protected, audited as `vault.read`), and Reveal auto-hides after 30 seconds. Admins also get users and
  tokens, projects and members, secret categories, per-member category grants, write-only secret entry, and audit.
  Google setup: create a Web-application OAuth client with redirect URI `<public origin>/ui/callback`.
- **Keeping this repo public.** No instance-specific detail may ever be committed: real hostnames, IPs, deploy
  notes and credentials belong in `.env` or `private/` (both gitignored). `public_safe.py` enforces it through git
  hooks in `.githooks/`: `pre-commit` scans the staged files, `commit-msg` the message, and `pre-push` every commit
  being pushed (so a `--no-verify` commit is still stopped). It refuses private IPs, SSH login targets, private
  keys, internal hostnames, credential assignments and known token formats, and reports the file and rule but never
  the matched text. After cloning, run `git config core.hooksPath .githooks`. Put your own domain and host names,
  one per line, in the gitignored `.public-safe-deny` and the hooks refuse those too. `test_public_safe.py` checks the
  tree and proves the hooks block bad commits and pushes.
