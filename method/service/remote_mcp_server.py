from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyUrl
from starlette.responses import JSONResponse, PlainTextResponse

from method.service.oidc import CompositeTokenVerifier, OidcTokenVerifier
from method.service.ui import register_ui
from method.service.store import AccessDenied, ProjectNotFound, Store, normalize_join_key, slug_from_join_key

METHOD_DIR = Path(__file__).resolve().parents[1]
HEADER_SCRIPT = METHOD_DIR / "protocol-header.sh"
SEARCH_SCRIPT = METHOD_DIR / "protocol-search.sh"
_CENTRAL_ENV = {**os.environ, "EVIDENCE_CENTRAL": "1"}  # header text points at MCP tools, not at local scripts
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62})[a-z0-9]$")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


def _validated_url(
    value: str,
    name: str,
    allow_loopback: bool = False,
    allow_identity_service: bool = False,
    allow_private: bool = False,
) -> str:
    parsed = urlparse(value)
    loopback = allow_loopback and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    try:
        private = allow_private and parsed.scheme == "http" and ipaddress.ip_address(parsed.hostname or "").is_private
    except ValueError:
        private = False
    internal_identity = (
        allow_identity_service and parsed.scheme == "http" and parsed.hostname == "identity" and parsed.port == 8080
    )
    if parsed.scheme != "https" and not (loopback or private or internal_identity):
        raise RuntimeError(f"{name} must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} is not a valid public URL")
    return value


def _store() -> Store:
    values = {
        "host": _env("PGHOST"),
        "port": os.environ.get("PGPORT", "5432"),
        "dbname": _env("PGDATABASE"),
        "user": _env("PGUSER"),
        "password": _env("PGPASSWORD"),
    }
    return Store(" ".join(f"{key}={_quote_conninfo(value)}" for key, value in values.items()))


def _quote_conninfo(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _identity() -> tuple[str, str | None, bool]:
    token = get_access_token()
    if token is None or not token.subject:
        raise AccessDenied("authenticated subject missing")
    claims = token.claims or {}
    return token.subject, claims.get("email"), "evidence:admin" in token.scopes


def _protocol_file(slug: str, content: str, command: str, *args: str) -> str:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("invalid project slug")
    with tempfile.TemporaryDirectory(prefix="evidence-protocol-") as temp:
        path = Path(temp) / slug / "EVIDENCE_PROTOCOL.md"
        path.parent.mkdir()
        path.write_text(content, encoding="utf-8")
        if command == "normalize":
            subprocess.run(
                ["bash", str(HEADER_SCRIPT), "sync", str(path)],
                env=_CENTRAL_ENV,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            return path.read_text(encoding="utf-8")
        if command == "header":
            subprocess.run(
                ["bash", str(HEADER_SCRIPT), "sync", str(path)],
                env=_CENTRAL_ENV,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            proc = subprocess.run(
                ["bash", str(HEADER_SCRIPT), "emit", str(path)],
                env=_CENTRAL_ENV,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        else:
            if not args:
                raise ValueError("search mode is required")
            proc = subprocess.run(
                ["bash", str(SEARCH_SCRIPT), args[0], str(path), *args[1:]],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        return proc.stdout


def create_server(store: Store | None = None, token_verifier: TokenVerifier | None = None) -> FastMCP:
    private_http = os.environ.get("MCP_INSECURE_PRIVATE_HTTP", "").lower() in {"1", "true", "yes"}
    public_url = AnyUrl(
        _validated_url(_env("MCP_PUBLIC_URL"), "MCP_PUBLIC_URL", allow_loopback=True, allow_private=private_http)
    )
    store = store or _store()
    # OIDC is optional: without MCP_OIDC_ISSUER_URL only per-user tokens (and the Google UI login) are accepted.
    issuer_setting = os.environ.get("MCP_OIDC_ISSUER_URL", "").strip()
    if issuer_setting and token_verifier is None:
        issuer = _validated_url(issuer_setting, "MCP_OIDC_ISSUER_URL", allow_loopback=True, allow_private=private_http)
        oidc = OidcTokenVerifier(
            issuer,
            _validated_url(
                _env("MCP_OIDC_JWKS_URL"),
                "MCP_OIDC_JWKS_URL",
                allow_loopback=True,
                allow_identity_service=True,
            ),
            _env("MCP_OIDC_AUDIENCE"),
        )
    else:
        issuer, oidc = issuer_setting or f"{public_url.scheme}://{public_url.host}", None
    verifier = token_verifier or CompositeTokenVerifier(oidc, store)
    allowed_hosts = [host.strip() for host in _env("MCP_ALLOWED_HOSTS").split(",") if host.strip()]
    allowed_origins = [origin.strip() for origin in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    if not allowed_hosts:
        raise RuntimeError("MCP_ALLOWED_HOSTS must contain the public host name")
    app = FastMCP(
        "Evidence",
        instructions="Read and update the authenticated user's central Evidence project protocols.",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyUrl(issuer),
            resource_server_url=public_url,
            required_scopes=["evidence:access"],
        ),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )

    @app.tool()
    def protocol_identity() -> dict:
        """Return the authenticated identity subject needed for project membership management."""
        subject, email, is_admin = _identity()
        store.upsert_user(subject, email)
        return {"subject": subject, "email": email, "is_admin": is_admin}

    @app.tool()
    def protocol_projects_list() -> list[dict]:
        """List projects the authenticated user can access."""
        subject, _, is_admin = _identity()
        return store.list_projects(subject, is_admin)

    @app.tool()
    def protocol_create_project(project_slug: str, name: str, initial_protocol: str) -> dict:
        """Create a project and its first immutable protocol revision; requires evidence:admin scope."""
        subject, email, is_admin = _identity()
        if not is_admin:
            raise AccessDenied("project creation requires evidence:admin scope")
        content = _protocol_file(project_slug, initial_protocol, "normalize")
        return store.create_project(project_slug, name, content, subject, email)

    @app.tool()
    def protocol_add_member(project_slug: str, member_subject: str, role: str) -> dict:
        """Grant a project role to an OIDC subject; only owners or service admins can manage membership."""
        subject, _, is_admin = _identity()
        return store.add_member(project_slug, member_subject, role, subject, is_admin)

    @app.tool()
    def protocol_remove_member(project_slug: str, member_subject: str) -> dict:
        """Revoke a project role while retaining the immutable audit event."""
        subject, _, is_admin = _identity()
        return store.remove_member(project_slug, member_subject, subject, is_admin)

    @app.tool()
    def protocol_get(project_slug: str) -> dict:
        """Read the current authoritative protocol and revision for an accessible project."""
        subject, _, is_admin = _identity()
        protocol = store.get_protocol(project_slug, subject, is_admin)
        store.touch_read(project_slug, subject, protocol["revision"], "mcp")
        return {
            "project_id": protocol["id"],
            "project_slug": protocol["slug"],
            "name": protocol["name"],
            "revision": protocol["revision"],
            "updated_at": protocol["updated_at"].isoformat(),
            "content": protocol["content"],
        }

    @app.tool()
    def protocol_header(project_slug: str) -> dict:
        """Read the generated header for the latest database revision."""
        subject, _, is_admin = _identity()
        protocol = store.get_protocol(project_slug, subject, is_admin)
        store.touch_read(project_slug, subject, protocol["revision"], "mcp")
        return {
            "project_slug": project_slug,
            "revision": protocol["revision"],
            "header": _protocol_file(project_slug, protocol["content"], "header"),
        }

    @app.tool()
    def protocol_sync_status(project_slug: str) -> dict:
        """Which project members have read the current protocol revision (current, behind, or never)."""
        subject, _, is_admin = _identity()
        return store.sync_status(project_slug, subject, is_admin)

    @app.tool()
    def protocol_search(
        project_slug: str,
        mode: str,
        pattern: str = "",
        phase_number: str = "",
    ) -> dict:
        """Search hypotheses, incidents, a phase, or body text in the current database revision."""
        if mode not in {"hypotheses", "incidents", "phase", "grep"}:
            raise ValueError("mode must be hypotheses, incidents, phase, or grep")
        if mode == "phase" and not phase_number.isdigit():
            raise ValueError("phase_number is required for phase searches")
        if mode == "grep" and not pattern:
            raise ValueError("pattern is required for grep searches")
        if len(pattern) > 256:
            raise ValueError("pattern exceeds 256 characters")
        subject, _, is_admin = _identity()
        protocol = store.get_protocol(project_slug, subject, is_admin)
        store.touch_read(project_slug, subject, protocol["revision"], "mcp")
        args = [mode]
        if mode == "phase":
            args.append(phase_number)
        elif mode == "grep":
            args.append(pattern)
        elif mode == "incidents" and pattern:
            args.append(pattern)
        return {
            "project_slug": project_slug,
            "revision": protocol["revision"],
            "result": _protocol_file(project_slug, protocol["content"], "search", *args),
        }

    @app.tool()
    def protocol_update(
        project_slug: str,
        content: str,
        expected_revision: int,
        summary: str,
    ) -> dict:
        """Write a new protocol revision; stale revisions conflict instead of overwriting another editor."""
        subject, email, _ = _identity()
        protocol = store.get_protocol(project_slug, subject)
        if protocol["role"] not in {"owner", "editor"}:
            raise AccessDenied("project edit access denied")
        normalized = _protocol_file(project_slug, content, "normalize")
        return store.update_protocol(
            project_slug,
            normalized,
            expected_revision,
            subject,
            summary,
            email,
        )

    @app.tool()
    def protocol_revision_history(project_slug: str, limit: int = 20) -> list[dict]:
        """List recent immutable revisions with author and timestamp."""
        subject, _, is_admin = _identity()
        return store.list_revisions(project_slug, subject, limit, is_admin)

    @app.tool()
    def protocol_members_list(project_slug: str) -> list[dict]:
        """List project members and roles for an accessible project."""
        subject, _, is_admin = _identity()
        return store.list_members(project_slug, subject, is_admin)

    @app.tool()
    def protocol_audit_history(project_slug: str, limit: int = 50) -> list[dict]:
        """List recent project audit events for an accessible project."""
        subject, _, is_admin = _identity()
        return store.list_audit(project_slug, subject, limit, is_admin)

    @app.tool()
    def protocol_approve_phase(
        project_slug: str,
        phase_number: int,
        expected_revision: int,
        approved: bool,
        note: str = "",
    ) -> dict:
        """Record an auditable phase approval against an exact protocol revision."""
        subject, _, _ = _identity()
        return store.record_approval(
            project_slug,
            phase_number,
            expected_revision,
            approved,
            note,
            subject,
        )

    @app.tool()
    def vault_categories() -> list[dict]:
        """List secret categories that can be granted to project members."""
        _identity()
        return store.list_categories()

    @app.tool()
    def vault_list(project_slug: str = "") -> list[dict]:
        """List secrets (names, categories, who they are shared with; never values) that you can read.
        Pass project_slug to see only those shared with that project."""
        subject, _, _ = _identity()
        return store.vault_list(subject, False, project_slug or None)

    @app.tool()
    def vault_get(name: str, project_slug: str = "") -> dict:
        """Decrypt one secret you can read; audited. Use the value programmatically (env var or command
        argument) and never print, quote, or log it."""
        subject, _, _ = _identity()
        return {"name": name, "value": store.vault_get(name, subject, project_slug or None)}

    @app.tool()
    def vault_put(name: str, category: str, value: str, project_slug: str = "", description: str = "") -> dict:
        """Create a secret you own, or rotate one you own. Optionally share it with a project you own or edit."""
        subject, _, is_admin = _identity()
        return store.vault_put(name, category, value, subject, is_admin, project_slug or None, description or None)

    @app.tool()
    def vault_delete(name: str) -> dict:
        """Delete a secret; its owner (or a service admin) only."""
        subject, _, is_admin = _identity()
        return store.vault_delete(name, subject, is_admin)

    @app.tool()
    def vault_share(name: str, projects: list[str], user_emails: list[str]) -> dict:
        """Set who a secret is shared with: whole projects (members read it per their category grants) and named
        users (by email). Replaces the previous share list for the projects you manage."""
        subject, _, is_admin = _identity()
        subjects = store.subjects_for_emails(user_emails)
        return store.set_secret_shares(name, projects, subjects, subject, is_admin)

    @app.tool()
    def vault_set_member_categories(project_slug: str, member_subject: str, categories: list[str]) -> dict:
        """Set which secret categories a project member may read; owners (or service admins) only."""
        subject, _, is_admin = _identity()
        return store.set_member_categories(project_slug, member_subject, categories, subject, is_admin)

    @app.tool()
    def protocol_join(join_key: str, name: str = "") -> dict:
        """Create the project for this repository identifier, or join it if it exists."""
        subject, email, _ = _identity()
        slug = slug_from_join_key(normalize_join_key(join_key))
        initial = _protocol_file(slug, f"# {name or join_key}\n", "normalize")
        return store.join_project(subject, join_key, name or join_key, initial)

    @app.custom_route("/api/join", methods=["POST"], include_in_schema=False)
    async def join(request):
        """Auto-register: a per-user token plus the repo's join key creates or joins a project."""
        auth = request.headers.get("authorization", "")
        row = await asyncio.to_thread(store.resolve_token, auth[7:]) if auth.lower().startswith("bearer ") else None
        if row is None:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        try:
            body = await request.json()
            join_key, name = str(body["join_key"]), str(body.get("name") or body["join_key"])[:200]
            slug = slug_from_join_key(normalize_join_key(join_key))
            imported = body.get("protocol")
            if imported is not None and not isinstance(imported, str):
                raise ValueError("protocol must be text")
            try:  # an existing local protocol becomes the first revision, but only if the project is new
                initial = await asyncio.to_thread(_protocol_file, slug, imported if imported and imported.strip() else f"# {name}\n", "normalize")
            except subprocess.CalledProcessError:
                return JSONResponse({"error": "the protocol text could not be processed"}, status_code=400)
            result = await asyncio.to_thread(store.join_project, row["subject"], join_key, name, initial)
            result["imported_protocol"] = bool(result["created"] and imported and imported.strip())
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "join_key (repository identifier) is required"}, status_code=400)
        return JSONResponse(result)

    @app.custom_route("/api/protocol/header", methods=["GET"], include_in_schema=False)
    async def protocol_header_rest(request):
        """Current generated protocol header for hooks: same bearer key as MCP, recorded as a read via `hook`."""
        auth = request.headers.get("authorization", "")
        token = await verifier.verify_token(auth[7:]) if auth.lower().startswith("bearer ") else None
        slug = request.query_params.get("project", "")
        if token is None or "evidence:access" not in token.scopes or not token.subject:
            return JSONResponse({"error": "invalid token"}, status_code=401)

        def build() -> dict:
            protocol = store.get_protocol(slug, token.subject, False)
            store.touch_read(slug, token.subject, protocol["revision"], "hook")
            return {"project_slug": slug, "name": protocol["name"], "revision": protocol["revision"],
                    "updated_at": protocol["updated_at"].isoformat(), "header": _protocol_file(slug, protocol["content"], "header")}

        try:
            return JSONResponse(await asyncio.to_thread(build), headers={"Cache-Control": "no-store"})
        except (AccessDenied, ProjectNotFound):
            return JSONResponse({"error": "project not found or access denied"}, status_code=403)

    @app.custom_route("/install.py", methods=["GET"], include_in_schema=False)
    async def installer(_request):
        """The open-source installer, so a fresh repository can set itself up with one curl."""
        path = METHOD_DIR.parent / "evidence_install.py"
        if not path.is_file():
            return JSONResponse({"error": "installer not available"}, status_code=404)
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/x-python",
                                 headers={"Cache-Control": "no-cache"})

    @app.custom_route("/api/vault/env", methods=["GET"], include_in_schema=False)
    async def vault_env(request):
        """Every secret the caller may read, as {NAME: value}, for `evidence_install.py run` (audited per read)."""
        auth = request.headers.get("authorization", "")
        token = await verifier.verify_token(auth[7:]) if auth.lower().startswith("bearer ") else None
        slug = request.query_params.get("project", "")
        if token is None or "evidence:access" not in token.scopes or not token.subject:
            return JSONResponse({"error": "invalid token"}, status_code=401)

        def collect() -> dict:
            names = [s["name"] for s in store.vault_list(token.subject, False, slug) if s["readable"]]
            return {name: store.vault_get(name, token.subject, slug) for name in names}

        try:
            values = await asyncio.to_thread(collect)
        except (AccessDenied, ProjectNotFound):
            return JSONResponse({"error": "project not found or access denied"}, status_code=403)
        return JSONResponse(values, headers={"Cache-Control": "no-store"})

    @app.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_request):
        try:
            with store.connect() as conn:
                conn.execute("SELECT 1")
        except psycopg.Error:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    ui_secret = os.environ.get("UI_SESSION_SECRET", "")
    google_id, google_secret = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if ui_secret and google_id and google_secret:  # the web UI is opt-in: all three settings must be present
        if len(ui_secret) < 32:
            raise RuntimeError("UI_SESSION_SECRET must be at least 32 characters")
        admins = frozenset(x.strip().lower() for x in os.environ.get("ADMIN_EMAILS", "").split(",") if x.strip())
        register_ui(app, store, str(public_url), google_id, google_secret, ui_secret, _protocol_file, admins)
    return app


def main() -> None:
    store = _store()
    store.initialize()
    create_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
