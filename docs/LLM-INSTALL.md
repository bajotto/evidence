# LLM install runbook

**Audience: an AI coding agent installing Evidence for a user.** Follow this file literally. It covers both modes: **Standalone** and **Team** (central service). Human-readable equivalents: [`INSTALL-STANDALONE.md`](INSTALL-STANDALONE.md), [`INSTALL-TEAM.md`](INSTALL-TEAM.md).

## How to use this file

A user can start you with this prompt:

```text
Read docs/LLM-INSTALL.md in the Evidence repository and install Evidence for me.
Ask me every question it lists before you change anything.
```

## 0. Non-negotiable rules

1. **Never print, echo, log, summarize or paste a secret**: `EVIDENCE_TOKEN` / any `evk_...` key, `VAULT_MASTER_KEY`, `UI_SESSION_SECRET`, `GOOGLE_CLIENT_SECRET`, database passwords, `.env` contents. Check that a variable is set with `[ -n "$EVIDENCE_TOKEN" ] && echo set`, never by printing it. Show key **names** only. If one leaks, say so without repeating it and tell the user to rotate it.
2. **Never guess** a destination, URL, slug, agent or mode. Ask.
3. **Dry-run before write.** Show the dry-run output, wait for explicit approval, then run for real. `join --dry-run` does not contact the service; the real `join` creates or joins the project there, so state that when asking for approval.
4. **Never write a secret into a repository file** or commit one. Do not commit `.env`.
5. **Do not skip a failed verification.** Report the failing check and its output (with secrets masked), then stop or fix the cause. Do not claim success without the verification in section 5.
6. **Do not modify** the user's agent settings beyond what the installers in this repository do, and never delete rules, hooks or MCP entries you did not create.
7. **Do not run** `docker compose up`, change DNS, firewall or TLS, create Google credentials, or restart services without the user's explicit go-ahead for that step.
8. Do not mark a Codex project `trusted` on the user's behalf.

## 1. Ask the user (all answers required before acting)

Ask these in one message. Use the defaults only if the user confirms them.

| # | Question | Needed for | Options / format |
|---|---|---|---|
| Q1 | Which mode? | all | `standalone` (one machine, no server) or `team` |
| Q2 | If `team`: which role? | team | `operator` (deploy the service), `member` (connect to an existing service), or both |
| Q3 | Which agent(s)? | all | any of `claude`, `devin`, `codex`, `cursor`, `trae` |
| Q4 | Absolute path of the project repository to configure | standalone project files, team member | existing directory |
| Q5 | Where is this Evidence repository checked out? | all | absolute path; if none, ask permission to `git clone https://github.com/bajotto/evidence.git <path>` |
| Q6 | Service URL | team | `https://<host>/mcp`; for operators, the planned public host name |
| Q7 | Is `EVIDENCE_TOKEN` already exported in the shell that launches the agent? | team member | yes/no. If no, the user must create a key in the UI (they do this; you must not ask them to paste it to you) |
| Q8 | Host/location for the server bundle, Google OAuth client status, admin emails | team operator | see section 4 |

If the user is unsure between modes, explain: standalone = file-based, zero infrastructure, one person or machine; team = shared protocol, members and roles, audit log, encrypted secrets vault, needs a server, a domain with TLS and a Google OAuth client.

## 2. Preflight (read-only)

Run and report the results. Stop on any `MISSING` that the chosen path requires.

```bash
cd <EVIDENCE_REPO>
git rev-parse --is-inside-work-tree && git log --oneline -1
python3 --version                      # need 3.11 or newer
command -v bash git                    # required
command -v jq || echo "jq MISSING"     # required for claude and devin installers only
command -v docker && docker compose version     # team operator only
command -v claude devin codex || true  # informational
git -C <PROJECT> remote get-url origin || echo "no origin: team join needs --join-key"
ls <PROJECT>/EVIDENCE_PROTOCOL.md 2>/dev/null || echo "no local protocol yet"
```

Also inspect the target for conflicts before writing anything:

```bash
ls -la <PROJECT>/.mcp.json <PROJECT>/.claude/rules <PROJECT>/.devin <PROJECT>/.windsurf/rules \
       <PROJECT>/.codex <PROJECT>/.cursor <PROJECT>/.trae <PROJECT>/AGENTS.md <PROJECT>/CLAUDE.md 2>&1 | head -40
```

Tell the user about anything pre-existing that the install would touch. If a standalone Evidence rule exists and the user wants Team mode, the installer refuses to write; report that, do not delete it.

## 3. Standalone install

Applies when Q1 = `standalone`. Run from `<EVIDENCE_REPO>`.

### 3.1 Per-agent command

| Agent | Command | Scope |
|---|---|---|
| `claude` | `./claude/install.sh` | global (`~/.claude`) |
| `devin` | `./devin/install.sh` | global (`~/.devin`) |
| `codex` | `./codex/install.sh` | global (`~/.codex`) |
| `cursor` | `./cursor/install.sh <PROJECT>` | project |
| `trae` | `./trae/install.sh <PROJECT>` | project |

Global installers change files in the user's home directory and merge into `~/.claude/settings.json` or `~/.devin/hooks.v1.json`. Tell the user exactly that and get approval first. They preserve existing settings and are idempotent. If one prints `WARNING: ... already exists and differs`, show the `diff` it suggests and ask whether to replace; never overwrite silently.

### 3.2 Project protocol

If `<PROJECT>/EVIDENCE_PROTOCOL.md` does not exist, ask permission, then:

```bash
cp <EVIDENCE_REPO>/method/PROJECT_PROTOCOL_TEMPLATE.md <PROJECT>/EVIDENCE_PROTOCOL.md
```

Then ask the user for the project name, current phase, status line, and first hypotheses with measurable acceptance criteria, and fill the placeholders. Keep the `PROTOCOL-HEADER:START` and `PROTOCOL-HEADER:END` markers. For `cursor` and `trae`, re-run their installer afterwards so the rule embeds the real header.

### 3.3 Agent-specific extras

- `claude`: offer `claude/CLAUDE.md.template` as `<PROJECT>/CLAUDE.md` (do not overwrite an existing `CLAUDE.md`; merge by hand with the user).
- `devin`: offer `devin/rules/PROJECT_RULE_TEMPLATE.md` as `<PROJECT>/.windsurf/rules/<name>.md`; keep `trigger: always_on`.
- `codex`: offer `codex/AGENTS.md.template` as `<PROJECT>/AGENTS.md`; tell the user the project must be trusted in Codex and that you will not do that for them.

### 3.4 Verify (standalone)

Run every check that applies, report each as PASS/FAIL:

```bash
bash method/test-protocol-header.sh
bash method/test-protocol-search.sh
bash method/service/test-protocol-mcp-server.sh
bash method/test-central-hooks.sh
bash claude/hooks/test-hooks.sh 2>/dev/null || bash ~/.claude/hooks/test-hooks.sh   # if claude installed
bash cursor/test-cursor-adapter.sh   # if cursor installed
bash trae/test-trae-adapter.sh       # if trae installed
bash method/protocol-header.sh check <PROJECT>/EVIDENCE_PROTOCOL.md
```

Additional agent checks: `claude` → `jq '.hooks | keys' ~/.claude/settings.json` must list `SessionStart`, `UserPromptSubmit`, `PostToolUse`; `devin` → `jq 'keys' ~/.devin/hooks.v1.json` likewise; `codex` → `codex mcp get evidence`; `cursor`/`trae` → the generated rule file and `mcp.json` exist.

Delivery into a live session can only be confirmed by starting a **new** agent session; tell the user to do that and what to look for (Claude: first system message contains `MANDATORY READING injected automatically by the global SessionStart hook`). Say plainly that you verified installation, not that the agent will comply.

## 4. Team install: operator

Applies when Q1 = `team` and Q2 includes `operator`. Do each step only after the user approves it. Full detail and rationale: [`INSTALL-TEAM.md` Part A](INSTALL-TEAM.md#part-a-operator).

### 4.1 Gather and check prerequisites

Confirm with the user: a Linux host with Docker and the Compose plugin; a public DNS name (`<HOST>`) pointing at it; a TLS reverse proxy that will forward `<HOST>` to `http://127.0.0.1:8000`; and a Google OAuth **Web application** client with redirect URI `https://<HOST>/ui/callback`. You cannot create the Google client. Tell the user to create it in Google Cloud Console and place the ID and secret directly into `.env` themselves, or into the environment, without pasting the secret into the chat.

### 4.2 Files

```bash
cd <EVIDENCE_REPO>/method/service
test -e .env && echo ".env exists: do not overwrite, edit in place" || cp .env.example .env
chmod 600 .env
```

### 4.3 Generate secrets without displaying them

Write generated values straight into `.env`; never print them. Example that fills the empty or placeholder entries:

```bash
python3 - <<'PY'
import base64, os, re, secrets, pathlib
p = pathlib.Path(".env"); t = p.read_text()
def setv(k, v):
    global t
    t = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", t) if re.search(rf"(?m)^{k}=", t) else t + f"\n{k}={v}\n"
pw = secrets.token_urlsafe(32)
for k in ("PGPASSWORD", "EVIDENCE_PGPASSWORD"): setv(k, pw)          # must be identical for the bundled database
setv("UI_SESSION_SECRET", secrets.token_urlsafe(48))
setv("VAULT_MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
p.write_text(t); print("secrets written to .env (values not shown)")
PY
```

Only run this if the corresponding keys are empty or still `replace-with-...`. If `VAULT_MASTER_KEY` already has a value, **do not replace it**: that would make existing vault data unrecoverable. Then set, by editing `.env`: `MCP_PUBLIC_URL=https://<HOST>/mcp`, `MCP_ALLOWED_HOSTS=<HOST>,<HOST>:443`, `ADMIN_EMAILS=<comma-separated emails>`, and make sure `PGUSER`/`EVIDENCE_PGUSER` and `PGDATABASE`/`EVIDENCE_PGDATABASE` match, `EVIDENCE_PGHOST=database`, `EVIDENCE_PGPORT=5432`. Ask the user to enter `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` themselves.

Remind the user, prominently: **back up `VAULT_MASTER_KEY` separately from the database now.** Losing it makes every vault secret unrecoverable. Do not read it back to them.

Validate required keys exist without showing values:

```bash
python3 - <<'PY'
import re, pathlib
t = pathlib.Path(".env").read_text()
req = ["PGDATABASE","PGUSER","PGPASSWORD","EVIDENCE_PGHOST","EVIDENCE_PGPORT","EVIDENCE_PGDATABASE","EVIDENCE_PGUSER","EVIDENCE_PGPASSWORD",
       "MCP_PUBLIC_URL","MCP_ALLOWED_HOSTS","VAULT_MASTER_KEY","UI_SESSION_SECRET","GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","ADMIN_EMAILS"]
v = dict(re.findall(r"(?m)^([A-Z_]+)=(.*)$", t))
for k in req:
    x = v.get(k, "")
    print(f"{k}: {'OK' if x and not x.startswith('replace-with') else 'MISSING/PLACEHOLDER'}")
print("DB passwords match:", v.get("PGPASSWORD") == v.get("EVIDENCE_PGPASSWORD"))
PY
```

### 4.4 Start (needs explicit go-ahead)

```bash
docker compose config --quiet && echo "compose OK"
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

Do not print the rendered `docker compose config` output (it expands secrets).

### 4.5 TLS and public check

The user configures the reverse proxy. After that:

```bash
curl -fsS https://<HOST>/health
```

Then ask the user to open `https://<HOST>/ui`, sign in with an `ADMIN_EMAILS` account, add their teammates under **Users**, and tell the teammates to follow the member steps (section 5). The first admin login is theirs to perform; you cannot do it.

### 4.6 Backup

Show the user the `pg_dump` command from [`INSTALL-TEAM.md` A8](INSTALL-TEAM.md#a8-back-up) and the key-backup reminder. Do not store dumps in the repository.

### 4.7 Verify (operator)

PASS only if all of: `docker compose ps` shows `database` and `evidence` healthy/running; `/health` returns success locally and through HTTPS; the user confirms an admin login works.

## 5. Team install: member

Applies when Q1 = `team` and Q2 includes `member`. Detail: [`INSTALL-TEAM.md` Part B](INSTALL-TEAM.md#part-b-member).

### 5.1 Key

The user creates their own key in the UI (**Evidence secret**, shown once). They must export it as `EVIDENCE_TOKEN` in the shell that launches the agent (typically a line in `~/.bashrc` or `~/.zshrc`). Check presence only:

```bash
[ -n "${EVIDENCE_TOKEN:-}" ] && echo "EVIDENCE_TOKEN is set" || echo "EVIDENCE_TOKEN is NOT set"
```

If it is not set, stop and tell the user what to do. Do not ask for the value.

### 5.2 Global hook refresh (claude, devin)

Ask approval, then run `./claude/install.sh` and/or `./devin/install.sh` from `<EVIDENCE_REPO>`. This makes the session header live from the service.

### 5.3 Join

For each selected agent, from `<EVIDENCE_REPO>`:

```bash
python3 evidence_install.py join --target <PROJECT> --agent <AGENT> --service-url <SERVICE_URL> --dry-run
```

The dry run does not contact the service and uses a placeholder slug. Show the full output and tell the user that the real run will create the project on the service (they become owner) or join it. After approval, repeat without `--dry-run`. Add `--join-key host/org/repo` only if the repository has no git `origin`. Report whether the project was **Created** or **Joined**, the slug, and the role. Note whether a local `EVIDENCE_PROTOCOL.md` was imported or deliberately not imported because the project already existed.

Error handling:

| Message | Meaning | Action |
|---|---|---|
| `set EVIDENCE_TOKEN ...` | variable not exported | back to 5.1 |
| `service returned HTTP 401` | key wrong or revoked | ask user to create a new key |
| `service returned HTTP 403/404` | no access or wrong slug | confirm project and membership with the user |
| `cannot reach service: ...` | DNS, network, or service down | check the URL, `curl -fsS <origin>/health` |
| `non-local service URLs must use HTTPS` | plain HTTP | need TLS, or an SSH tunnel to `127.0.0.1` |
| `no git origin remote` | no `origin` | pass `--join-key` |
| `standalone Evidence guidance conflicts ...` | old standalone rule found | tell user which file; do not delete; they convert it |
| `an incompatible MCP server named 'evidence' already exists` | different existing entry | show it, ask the user how to reconcile |

### 5.4 Verify (member)

```bash
ls <PROJECT>/.evidence/project.json
# agent config exists for the chosen agent: .mcp.json | .devin/mcp_config.json | .codex/config.toml | .cursor/mcp.json | .trae/mcp.json
curl -fsS -o /dev/null -w "header endpoint HTTP %{http_code}\n" \
  -H "Authorization: Bearer $EVIDENCE_TOKEN" "<ORIGIN>/api/protocol/header?project=<SLUG>"
grep -c 'EVIDENCE_TOKEN' <PROJECT>/.mcp.json 2>/dev/null   # config references the variable by name
grep -rE 'evk_[A-Za-z0-9_-]{8,}' <PROJECT> --exclude-dir=.git -l || echo "no key written to disk"
```

`<ORIGIN>` is the service URL without the trailing `/mcp`. Expected: HTTP 200, the config references `EVIDENCE_TOKEN` by name, and the last command prints `no key written to disk`. The `-o /dev/null` and `-w` flags keep the response and key out of the output.

Then ask the user to start a new agent session in the project from a shell where `EVIDENCE_TOKEN` is set and request: "Call the evidence `protocol_header` tool for this project and state the current phase." You cannot verify that yourself without being that agent session; say so if you cannot.

Codex: remind the user that project config loads only for trusted projects.

## 6. Report back

End with a short report: mode and role; each file created or changed (paths only); each verification with PASS/FAIL; anything you could not verify (live agent session, public HTTPS, Google login, backup restore); and the user's remaining manual steps. Do not include any secret value. State that Team mode is a pilot and that live client OAuth and restore automation are not verified.

## 7. Stop conditions

Stop and ask the user, instead of continuing, when: a preflight requirement is missing; a file would be overwritten with different content; a settings file is malformed JSON or TOML; the installer refuses with a conflict; a secret would have to be displayed or pasted into chat; `VAULT_MASTER_KEY` would be replaced; a verification fails and the cause is not clear from the table above.
