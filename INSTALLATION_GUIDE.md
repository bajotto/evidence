# Installation Guide

Evidence has two deployment models. Pick one, then open its guide.

## How to read this repository

This repository is the **reference code**, not an installation. It holds the method, the hooks, the installers, the templates and the service source. It never holds a client's data. Every implementation is a separate **instance** built from it and run on the client's own machine or infrastructure:

| | Comes from this repository | Created and kept by the client |
|---|---|---|
| Standalone | method docs, hooks, installers, templates | hooks and rules copied into the agent's home (`~/.claude`, `~/.devin`, ...), plus each project's `EVIDENCE_PROTOCOL.md` |
| Team | all of the above, plus the service source in `method/service/` | the running service, its PostgreSQL database (revisions, approvals, audit, vault, members) and each member's local connection |

What follows from this:

- **Keep the checkout.** Installers copy from it, and some adapters point at scripts inside it. To update an instance, `git pull` and re-run the installers; for Team, also rebuild and redeploy the service.
- **An instance can drift from the repository.** An installer that finds a different copy of a method doc warns and does not overwrite it. Diff it and decide.
- **Nothing from an instance goes back into the repository.** Protocols, hostnames, keys and paths of a real deployment stay on the client side; a guard blocks them from public commits.

| I want to... | Open |
|---|---|
| Use Evidence alone, offline, with no server | [`docs/INSTALL-STANDALONE.md`](docs/INSTALL-STANDALONE.md) |
| Run a shared service for a team (protocol, members, audit, secrets vault) | [`docs/INSTALL-TEAM.md`](docs/INSTALL-TEAM.md) |
| Connect my machine to a Team service someone else runs | [`docs/INSTALL-TEAM.md`, Part B](docs/INSTALL-TEAM.md#part-b-member) |
| Have an AI agent do the installation for me | [`docs/LLM-INSTALL.md`](docs/LLM-INSTALL.md) |

## Quick comparison

| | Standalone | Team |
|---|---|---|
| Source of truth | `EVIDENCE_PROTOCOL.md` per project | PostgreSQL behind an MCP service |
| Infrastructure | none | Docker, domain with TLS, Google OAuth client |
| Entry point | `./claude/install.sh`, `./devin/install.sh`, `./codex/install.sh`, `./cursor/install.sh DIR`, `./trae/install.sh DIR` | `docker compose up` in `method/service/`, then `python3 evidence_install.py join ...` |

## Rules that apply to both

- Always preview: installers support `--dry-run` for local files, and global installers print every path they touch. `join --dry-run` also skips the service call, so nothing is created or joined remotely.
- Installers preserve existing configuration, never delete rules, and refuse conflicting files.
- Keys and secrets are never written into a repository. Team keys are read from the `EVIDENCE_TOKEN` environment variable.
- Delivery of rules to the agent is verified by tests; compliance by the agent is not guaranteed. See [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md).

## Moving from Standalone to Team

Run `join` in a repository that has an `EVIDENCE_PROTOCOL.md`. If the project is new on the service, the file is imported as revision 1; the central copy then becomes authoritative. The installer stops if a standalone rule in that repository would conflict, so convert or remove that rule first.

## Older flow: `project`

`evidence_install.py project --target DIR --agent AGENT --service-url URL --project-slug SLUG --confirm-project-linked` configures a repository for a slug that already exists centrally, without a personal key (OAuth-based clients). It does not create anything on the service. Most users want `join`; the details are in [`docs/INSTALL-TEAM.md`](docs/INSTALL-TEAM.md#reference).

## Validation commands

See the Tests section of the [README](README.md#tests).
