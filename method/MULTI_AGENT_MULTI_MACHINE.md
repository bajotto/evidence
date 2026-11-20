# Multi-agent and multi-machine use

Evidence has two distinct modes; choose one explicitly for each project.

## Standalone: Git remains the source of truth

With standalone adapters, the running protocol lives in the project's `EVIDENCE_PROTOCOL.md`. Git history provides cross-user attribution and multi-machine synchronization (`git log`, `git blame`, push/pull). No central service is needed. This is the established workflow and remains suitable for offline projects.

## Central service: PostgreSQL is the source of truth (pilot)

The central MCP pilot stores each protocol and its immutable revisions in PostgreSQL. Users authenticate with OIDC-issued MCP access tokens and receive roles per project. Each write includes the revision the editor read; stale edits conflict rather than silently overwriting. Local Markdown is only a snapshot after an explicit import.

This deliberately replaces Git as the authoritative collaboration/audit store for central-mode projects. Keep the Git export policy explicit; do not edit both the database and Markdown snapshots as independent sources of truth.

The service implementation is still a pilot. Its Compose bundle includes Keycloak, but the operator must configure a realm, federate Google, assign scopes/audience, and constrain client registration. Backup/restore automation, rate limiting, live client OAuth validation, and production operations also remain incomplete. Do not expose the pilot to the internet or scale until these gaps are closed and a 3–5 project pilot has passed 100% with explicit approval.

Free distribution refers to the MIT-licensed code. A self-hosting operator still pays for or supplies the server, network, domain/TLS operations, identity-provider configuration, backups, and maintenance.
