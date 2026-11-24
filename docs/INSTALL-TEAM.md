# Install: Team (central service)

Team mode runs one self-hosted Evidence service. It keeps every project's protocol and revisions, the members and their roles, the audit log and an encrypted secrets vault in PostgreSQL. Agents reach it over authenticated MCP; people use a web UI.

There are two separate jobs, usually done by different people:

| Part | Who | When |
|---|---|---|
| **A. Operator**: deploy and configure the service | one admin | once |
| **B. Member**: connect a machine and a repository | every user | once per person, once per repository |

> Automating this with an AI agent? Give it [`LLM-INSTALL.md`](LLM-INSTALL.md); it carries the same steps as a checked runbook with stop conditions.

**Status.** This is a pilot. Google sign-in, personal keys, the vault, the UI, auto-join and the hooks are implemented and covered by tests; a LAN staging deployment passed a full token-to-MCP end-to-end run. Still open: live verification of each agent against a public HTTPS deployment, backup/restore automation, rate limiting and production monitoring. Do not call it production until you have run those yourself. Details: [`../method/service/README.md`](../method/service/README.md).

## Contents

- [Part A. Operator](#part-a-operator)
  1. [Requirements](#a1-requirements)
  2. [Get the files](#a2-get-the-files)
  3. [Create the Google OAuth client](#a3-create-the-google-oauth-client)
  4. [Configure `.env`](#a4-configure-env)
  5. [Start the service](#a5-start-the-service)
  6. [Put TLS in front](#a6-put-tls-in-front) (and optional [HTTPS for a LAN-only deployment](#a6b-optional-https-for-a-lan-only-deployment))
  7. [First login and users](#a7-first-login-and-users)
  8. [Back up](#a8-back-up)
- [Part B. Member](#part-b-member)
  1. [Get your key](#b1-get-your-key)
  2. [Prepare the machine](#b2-prepare-the-machine)
  3. [Join a repository](#b3-join-a-repository)
  4. [Verify](#b4-verify)
  5. [Use the vault](#b5-use-the-vault)
- [Reference](#reference)
- [Upgrade](#upgrade)
- [Troubleshooting](#troubleshooting)

---

## Part A. Operator

### A1. Requirements

| Needed | Notes |
|---|---|
| A Linux host with Docker Engine and the Compose plugin | `docker compose version` must work |
| A public DNS name, for example `evidence.example.com` | pointing at the host |
| TLS termination | any reverse proxy (Caddy, nginx, Traefik, Coolify, Cloudflare Tunnel). The service listens on plain HTTP at `127.0.0.1:8000` |
| A Google account able to create an OAuth client | Google Cloud Console |
| `python3` and `git` on the machine you run the commands from | to generate secrets and fetch files |

Hosting, DNS, TLS, Google administration, backups and upkeep are yours. The code is MIT-licensed; that does not make infrastructure free.

### A2. Get the files

Recommended: use a clone, so upgrades are `git pull`.

```bash
git clone https://github.com/bajotto/evidence.git ~/evidence
cd ~/evidence/method/service
cp .env.example .env
chmod 600 .env
```

Alternative: let the installer lay down a standalone bundle. It never starts Docker, never overwrites a differing file and never touches DNS or firewall.

```bash
python3 evidence_install.py server --target /srv/evidence --dry-run   # review the listed paths
python3 evidence_install.py server --target /srv/evidence
cd /srv/evidence/evidence-server && cp .env.example .env && chmod 600 .env
```

The bundle path cannot be upgraded in place because the installer refuses to overwrite changed files. Prefer the clone for anything long-lived.

### A3. Create the Google OAuth client

1. Google Cloud Console → **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type **Web application**.
3. **Authorized redirect URI:** `https://evidence.example.com/ui/callback` (your public origin plus `/ui/callback`, exactly).
4. Copy the client ID and secret into `.env` in the next step. Treat the secret like a password.

Only accounts you allow can enter: an address listed in `ADMIN_EMAILS`, or one an admin created in the UI first. Unknown Google accounts are refused.

### A4. Configure `.env`

Generate every secret value locally; never reuse one.

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(32))"     # for each password
python3 -c "import secrets;print(secrets.token_urlsafe(48))"     # UI_SESSION_SECRET
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"   # VAULT_MASTER_KEY
```

Edit `.env`. Required for the standard setup:

| Variable | Value |
|---|---|
| `PGDATABASE`, `PGUSER`, `PGPASSWORD` | database created by the bundled `database` container |
| `EVIDENCE_PGHOST` | `database` (the bundled container) |
| `EVIDENCE_PGPORT` | `5432` |
| `EVIDENCE_PGDATABASE`, `EVIDENCE_PGUSER`, `EVIDENCE_PGPASSWORD` | **must equal** the three `PG*` values above when you use the bundled database |
| `MCP_PUBLIC_URL` | `https://evidence.example.com/mcp` |
| `MCP_ALLOWED_HOSTS` | `evidence.example.com,evidence.example.com:443` |
| `MCP_ALLOWED_ORIGINS` | leave empty unless a browser client needs it |
| `MCP_INSECURE_PRIVATE_HTTP` | `false`; `true` only for LAN staging without TLS (see [A6](#a6-put-tls-in-front)) |
| `VAULT_MASTER_KEY` | the base64 value generated above |
| `UI_SESSION_SECRET` | 32+ random characters |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | from step A3 |
| `ADMIN_EMAILS` | comma-separated Google addresses of the administrators |

Ignore `KC_*`, `KEYCLOAK_*` and `OIDC_PUBLIC_URL` unless you add the optional Keycloak overlay (see [Reference](#reference)).

**Back up `VAULT_MASTER_KEY` now, somewhere separate from the database** (a password manager or sealed secret store). It encrypts every vault value; losing it makes them unrecoverable and there is no reset.

Using an external PostgreSQL instead: point `EVIDENCE_PGHOST` and `EVIDENCE_PGPORT` at it, set the other `EVIDENCE_PG*` values for it, and remove the `database` service from the Compose file.

### A5. Start the service

From the directory that holds `compose.yaml` (`method/service/` in a clone, `evidence-server/` in a bundle):

```bash
docker compose config --quiet && echo "compose config OK"
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health && echo
```

`docker compose config` fails fast with the name of any variable you forgot. The app waits for the database healthcheck; the first start applies the schema.

Ports: the app binds only `127.0.0.1:8000`. PostgreSQL publishes no host port. Do not publish either; the proxy in the next step is the only public path.

### A6. Put TLS in front

Point the reverse proxy for `evidence.example.com` at `http://127.0.0.1:8000` and forward the `Host` header unchanged. Minimal Caddy example:

```text
evidence.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Check from another machine:

```bash
curl -fsS https://evidence.example.com/health && echo
```

If an authenticated request to `/mcp` is rejected with HTTP 421 (invalid `Host`) or 403 (invalid `Origin`), `MCP_ALLOWED_HOSTS` or `MCP_ALLOWED_ORIGINS` does not match what clients send (unauthenticated requests get 401 first); fix `.env` and run `docker compose up -d`.

Staging on a bare LAN IP (no TLS possible): set `MCP_INSECURE_PRIVATE_HTTP=true` in `.env`. The server then accepts an `http://` `MCP_PUBLIC_URL` (and OIDC issuer) only when it points at a private address; public addresses still require HTTPS. Never set it on a real deployment. Clients still refuse that URL (next paragraph), so members of a LAN staging service connect through a tunnel.

Client tools refuse plain `http://` for anything except `localhost`, `127.0.0.1` and `::1`. For a private test without TLS, tunnel the port (`ssh -L 8000:127.0.0.1:8000 host`) and use `http://127.0.0.1:8000/mcp` as the service URL.

### A6b. Optional: HTTPS for a LAN-only deployment

Skip this if the service is already reachable from the internet behind a normal certificate. Use it when the team is on a LAN and the server must not be exposed publicly, but you still need HTTPS (Google login and the clients require it; see [why](#why-https-on-a-lan)).

The idea: own a real domain, point a name at the server's **private** IP, and obtain the certificate with the DNS-01 challenge. Let's Encrypt then validates through a DNS record, never by connecting to your server, so nothing has to be open to the internet.

1. **Name.** Choose `evidence.example.com` under a domain you control (a subdomain of your company domain is fine).
2. **DNS record.** Create `A evidence.example.com -> 192.168.50.x` (the server's LAN IP). Some routers drop public DNS answers that point to private ranges (DNS rebinding protection). If lookups fail from a LAN machine, add the same record to your local DNS (router, Pi-hole, dnsmasq) instead, or allow the name in the rebinding exceptions.
3. **Caddy with a DNS plugin.** DNS-01 needs a Caddy build that includes your DNS provider's module (for example `caddy-dns/cloudflare`), built with `xcaddy build --with github.com/caddy-dns/cloudflare` or the official `caddy:builder` image. Your provider's module name and token scope are in its own documentation.
4. **Caddyfile** (Cloudflare shown; replace the `dns` line for another provider):

```text
evidence.example.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    reverse_proxy 127.0.0.1:8000
}
```

   After building, confirm the module is present with `caddy list-modules | grep cloudflare`.

   Pass `CF_API_TOKEN` to Caddy as an environment variable that is set **before Caddy starts** (otherwise Cloudflare rejects the requests). Use one API token with Zone:Read and DNS:Edit on that single zone. It is a secret: do not put it in the Caddyfile or in this repository. If certificate issuance fails while checking DNS propagation, add `resolvers 1.1.1.1` inside the `tls` block.
5. **Firewall.** Allow 443 from the LAN only, for example `sudo ufw allow from 192.168.50.0/24 to any port 443 proto tcp`, and do not forward 443 on your router. Keep `127.0.0.1:8000` unpublished as before.
6. Continue with `.env`, Google OAuth and everything else exactly as written, using `https://evidence.example.com` as the public origin.

Verify from a LAN machine and from outside:

```bash
getent hosts evidence.example.com                # LAN: the private IP
curl -fsS https://evidence.example.com/health    # LAN: succeeds with a valid certificate
# from outside the LAN the name may resolve, but the connection must fail or time out
curl -m 5 -fsS https://evidence.example.com/health || echo "not reachable from outside (expected)"
```

Alternatives: **Tailscale** (HTTPS certificates must be enabled for the tailnet; then `tailscale serve --bg --https=443 http://127.0.0.1:8000` publishes the service to tailnet members only, with a `*.ts.net` certificate and no open ports; Serve accepts only loopback targets. Confirm that Google accepts the `*.ts.net` host as a redirect URI in your account before relying on it), or an **internal CA** (mkcert, step-ca; every client machine must trust it, and a private hostname such as `evidence.lan` may be refused as a Google redirect URI, so prefer a domain you own).

#### Why HTTPS on a LAN

- Google sign-in for the UI needs an `https://` redirect URI. Per Google's OAuth client rules, plain HTTP is allowed only for localhost and the host cannot be a raw IP address, so `http://192.168.50.x` is rejected and users could not create their keys. Google also documents that origin hosts must be on the public suffix list; whether that applies to redirect URIs is not confirmed, so use a domain you own.
- Personal keys and vault values travel in headers and responses. Over HTTP anyone on the same network segment can read them.
- `evidence_install.py join` and `run` refuse non-loopback `http://` by design.

### A7. First login and users

1. Open `https://evidence.example.com/ui` and sign in with an `ADMIN_EMAILS` Google account. That account is created as admin on first login.
2. **Users**: add each teammate by Google email. Anyone not listed, and not in `ADMIN_EMAILS`, is refused at login.
3. Optional now or later: create secret **categories** and grant them per project member.
4. Tell members to follow [Part B](#part-b-member). They create their own key; admins never see it.

### A8. Back up

Two things, stored separately:

```bash
# database (run where compose.yaml is; names come from .env)
docker compose exec -T database pg_dump -U "$PGUSER" "$PGDATABASE" > evidence-$(date +%F).sql
```

and `VAULT_MASTER_KEY`. A database dump without the key restores everything except the ability to decrypt vault values. Test a restore into a scratch database before you rely on it; restore automation is not provided.

---

## Part B. Member

### B1. Get your key

1. Sign in at `https://evidence.example.com/ui` with your Google account (an admin must have added you).
2. Open **Evidence secret** → create a key. It looks like `evk_...`.
3. Copy it immediately: it is shown **once** and only its SHA-256 is stored. You may have up to 10 active keys and can revoke any of them.

This key only identifies you. It is not a vault secret and never lives in the vault.

### B2. Prepare the machine

Requirements: `python3` 3.11+, `git`, and a clone of this repository (`git clone https://github.com/bajotto/evidence.git ~/evidence`).

Put the key in the environment of the shell that launches your agent. Never write it in a file inside a repository.

```bash
# add to ~/.bashrc or ~/.zshrc, then open a new terminal
export EVIDENCE_TOKEN='evk_...'
```

Do not paste the real value into chat, tickets or commits. A GUI-launched agent (Cursor, Trae) does not read your shell profile: start it from a terminal, or set the variable in the OS login environment.

**Claude Code and Devin: refresh the global hook (one time per machine).** It makes the session header come live from the service instead of a local file.

```bash
cd ~/evidence
./claude/install.sh     # Claude Code
./devin/install.sh      # Devin CLI
```

Without `EVIDENCE_TOKEN` in the environment the hook cannot fetch the header and says so in the session.

### B3. Join a repository

In each repository, from a terminal where `EVIDENCE_TOKEN` is set. Always preview first:

```bash
cd /path/to/your/repo
python3 ~/evidence/evidence_install.py join --target . --agent claude \
  --service-url https://evidence.example.com/mcp --dry-run
```

`--dry-run` neither writes files nor contacts the service, so nothing is created or joined; it needs no `EVIDENCE_TOKEN` and no network. The preview shows the files that would be written, with a placeholder project slug (the real slug is derived by the service). Review the listed paths, then run it again without `--dry-run`:

```bash
python3 ~/evidence/evidence_install.py join --target . --agent claude \
  --service-url https://evidence.example.com/mcp
```

`--agent` is one of `claude`, `devin`, `codex`, `cursor`, `trae`. Run it once per agent you use in that repository.

What happens:

1. The repository's git `origin` URL becomes the join key. No origin? Pass `--join-key host/org/repo`.
2. If no project has that key, it is **created** and you become `owner`. A local `EVIDENCE_PROTOCOL.md`, if present and under 2 MB, is imported as revision 1.
3. If the project exists, you are added as `editor`. Re-running is idempotent and never downgrades a role. A local protocol is **not** imported over an existing central one; compare in the UI.
4. Files are written in the repository (table below). The key is referenced by variable name only and is never written to disk.

| Agent | MCP config | Rule/guidance |
|---|---|---|
| Claude Code | `.mcp.json` | `.claude/rules/evidence-central.md` |
| Devin CLI | `.devin/mcp_config.json` | `.windsurf/rules/evidence-central.md` |
| Codex CLI | `.codex/config.toml` | managed section in `AGENTS.md` |
| Cursor | `.cursor/mcp.json` | `.cursor/rules/evidence-central.mdc` |
| Trae | `.trae/mcp.json` | `.trae/rules/evidence-central.md` |

Plus `.evidence/project.json` (service URL and project slug) in every case.

The installer stops, without writing, if it finds standalone Evidence guidance that would conflict (for example `CLAUDE.md` mentioning `EVIDENCE_PROTOCOL.md`, or `.windsurf/rules/evidence.md`). Review that file and convert or remove it yourself; the installer never deletes rules.

These generated files contain no secret, so they can be committed. A teammate who pulls them still has to run `join` once to be added as a member.

Codex loads project config only for trusted projects; the installer never changes trust.

### B4. Verify

```bash
# 1. The service answers and your key is accepted
curl -fsS -H "Authorization: Bearer $EVIDENCE_TOKEN" \
  "https://evidence.example.com/api/protocol/header?project=<slug>" | head -c 400; echo
```

Use the slug printed by `join` (`Joined project <slug> as editor`). You should see the protocol header text, not an error.

2. Start the agent in the repository and ask: *"Call the evidence `protocol_header` tool for this project and tell me the current phase."* A correct answer proves the MCP path.
3. In the web UI, the protocol page lists you among the members and shows whether you are in sync.

Expected failures: HTTP 401 means the key is wrong, revoked or not exported in this shell; HTTP 403 means you are not a member of that project or the slug is wrong.

### B5. Use the vault

Secrets you may read are injected as environment variables into a command, never printed:

```bash
python3 ~/evidence/evidence_install.py run --target . -- ./deploy.sh
```

`--target` must be a repository already joined (it reads `.evidence/project.json`). The command inherits your environment plus the permitted secrets. Create, share and rotate secrets in the UI under **Secrets**; **Reveal** auto-hides after 30 seconds and every read is audited as `vault.read`.

Who can read a secret: its owner; users it was shared with directly; and members of a project it is shared with if they own that project or were granted the secret's category there. Admins can manage access but cannot read values unless they qualify the same way.

---

## Reference

**Installer subcommands** (`python3 evidence_install.py ...`)

| Command | Purpose | Key flags |
|---|---|---|
| `join` | Create or join a project by repository, write agent config | `--target` `--agent` `--service-url` `[--join-key] [--name] [--token-env] [--dry-run]` |
| `run` | Run a command with permitted secrets as env vars | `[--target] [--token-env] -- <cmd>` |
| `server` | Lay down the server bundle | `--target` `[--dry-run]` |
| `project` | Older flow for a project already provisioned centrally; uses OAuth, no personal key | `--target` `--agent` `--service-url` `--project-slug` `--confirm-project-linked` `[--dry-run]` |

`--token-env` changes the variable name (default `EVIDENCE_TOKEN`). Service URLs must be `https://`, or `http://` only for loopback, with no credentials, query or fragment.

**HTTP endpoints**

| Path | Auth | Use |
|---|---|---|
| `/health` | none | liveness |
| `/ui` | Google login | web UI |
| `/mcp` | bearer key or OIDC token | Streamable HTTP MCP |
| `/api/join` | bearer key | auto-join |
| `/api/protocol/header` | bearer key | live header for hooks |
| `/api/vault/env` | bearer key | secrets as env for `run` |
| `/install.py` | none | serves `evidence_install.py`, so a fresh machine can `curl -fsS https://<host>/install.py -o evidence_install.py` instead of cloning |

**MCP tools:** `protocol_get`, `protocol_header`, `protocol_search`, `protocol_update` (needs `expected_revision`; a stale write is rejected, re-read and retry), `protocol_approve_phase`, `protocol_set_phase_gate` (owner), `protocol_create_project`, `protocol_join`, `protocol_identity`, `protocol_projects_list`, `protocol_add_member`, `protocol_remove_member`, `protocol_members_list`, `protocol_audit_history`, `protocol_revision_history`, `protocol_sync_status`. Vault tools: `vault_list`, `vault_get`, `vault_put`, `vault_share`, `vault_delete`, `vault_categories`, `vault_set_member_categories`. Roles: `owner`, `editor`, `reader`; the last owner cannot be removed.

**Hook tuning (client side):** `EVIDENCE_HOOK_CACHE_TTL` (default 60 s) and `EVIDENCE_HOOK_TIMEOUT` (default 3 s). Offline, the hook shows the last copy marked stale.

**Optional Keycloak overlay.** Lets MCP clients use OAuth instead of a personal key: `docker compose -f compose.yaml -f compose.keycloak.yaml up -d --build`, set the `KC_*`, `KEYCLOAK_*` and `OIDC_PUBLIC_URL` variables, then create the `evidence` realm, configure Google as its identity provider, and set the `evidence:access` / `evidence:admin` scopes and the `evidence-mcp` audience. The realm is not auto-provisioned. Follow [`../method/service/README.md`](../method/service/README.md); live OAuth against each agent is not yet verified, which is why personal keys are the supported path here.

### Phase gate (optional, per project)

By default a phase in the protocol is only text. An owner can make it a rule: `protocol_set_phase_gate(project_slug, true)`. While the gate is on, `protocol_update` (and the web editor) refuse a revision when:

- it moves to the next phase and the latest decision for the current phase is not an approval, or that approval predates the revision that entered the phase;
- it skips a phase, or removes the declared phase.

Moving back to an earlier phase is allowed and recorded as `phase.regressed`. Only owners can approve while the gate is on, so an editor cannot approve their own advance. The phase is read from the protocol the same way the header does (the **Status:** paragraph, else the last `### Phase N` heading). Turning the gate on records the current phase as the starting point; turning it off is audited. This proves a human approved the phase, not that the pilot results were true. See [`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).

## Upgrade

```bash
cd ~/evidence && git pull
cd method/service && docker compose up -d --build
```

Take a database backup first (A8). Members re-run `./claude/install.sh` / `./devin/install.sh` after pulling.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker compose config` names a missing variable | `.env` incomplete | Fill that variable |
| App container restarts | DB password in `EVIDENCE_PG*` differs from `PG*`, or DB not healthy | Align them; `docker compose logs evidence database` |
| `/health` fails through the proxy but works on `127.0.0.1:8000` | Proxy target or `Host` header | Fix proxy |
| `/mcp` rejects with a host/origin error (421/403) | `MCP_ALLOWED_HOSTS` mismatch | Match the public host, restart |
| Google error `redirect_uri_mismatch` | URI in Google Console differs | Set exactly `https://<host>/ui/callback` |
| Login refused for a valid Google account | Email not in `ADMIN_EMAILS` and not created in Users | Add the user |
| `join`: `set EVIDENCE_TOKEN ...` | Variable not exported in this shell | `export EVIDENCE_TOKEN=...` |
| `join`: `HTTP 401` | Key wrong or revoked | Create a new key |
| `join`: `non-local service URLs must use HTTPS` | Plain HTTP to a non-loopback host | Add TLS, or tunnel to `127.0.0.1` |
| `join`: `no git origin remote` | Repo has no `origin` | Pass `--join-key host/org/repo` |
| `join`: `standalone Evidence guidance conflicts` | Old standalone rule present | Convert or remove it manually, rerun |
| `join`: `incompatible MCP server named 'evidence'` | Different `evidence` entry already in the config | Reconcile by hand |
| Session shows `EVIDENCE_TOKEN is not set` | Agent launched without the variable | Export it and relaunch from that shell |
| Vault values unreadable after restore | `VAULT_MASTER_KEY` differs from the original | Restore the original key |
