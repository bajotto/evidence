from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62})[a-z0-9]$")
MAX_PROTOCOL_BYTES = 2_000_000
LAST_USED_REFRESH_SECONDS = 300
READ_REFRESH_SECONDS = 300


class RevisionConflict(Exception):
    def __init__(self, current_revision: int):
        self.current_revision = current_revision
        super().__init__(f"stale protocol revision; current revision is {current_revision}")


class ProjectNotFound(Exception):
    pass


class AccessDenied(Exception):
    pass


class Store:
    def __init__(self, conninfo: str):
        self.conninfo = conninfo

    def connect(self):
        return psycopg.connect(self.conninfo, row_factory=dict_row)

    def initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as conn:
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(statement)

    def upsert_user(self, subject: str, email: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO users (subject, email) VALUES (%s, %s) "
                "ON CONFLICT (subject) DO UPDATE SET email = COALESCE(EXCLUDED.email, users.email)",
                (subject, email),
            )

    def create_project(self, slug: str, name: str, content: str, actor: str, email: str | None = None) -> dict:
        validate_protocol(content)
        if not SLUG_RE.fullmatch(slug):
            raise ValueError("slug must be 3-64 lowercase letters, digits, or hyphens")
        if not name.strip() or len(name) > 200:
            raise ValueError("name must contain 1-200 characters")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO users (subject, email) VALUES (%s, %s) "
                "ON CONFLICT (subject) DO UPDATE SET email = COALESCE(EXCLUDED.email, users.email)",
                (actor, email),
            )
            project_id = uuid.uuid4()
            project = conn.execute(
                "INSERT INTO projects (id, slug, name, created_by) VALUES (%s, %s, %s, %s) "
                "RETURNING id, slug, name",
                (project_id, slug, name, actor),
            ).fetchone()
            conn.execute(
                "INSERT INTO project_memberships (project_id, subject, role) VALUES (%s, %s, 'owner')",
                (project_id, actor),
            )
            conn.execute(
                "INSERT INTO protocols (project_id, content, revision, updated_by) VALUES (%s, %s, 1, %s)",
                (project_id, content, actor),
            )
            conn.execute(
                "INSERT INTO protocol_revisions (project_id, revision, content, actor_subject, summary) "
                "VALUES (%s, 1, %s, %s, 'initial import')",
                (project_id, content, actor),
            )
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, revision) "
                "VALUES (%s, %s, 'protocol.created', 1)",
                (project_id, actor),
            )
        return {**project, "id": str(project["id"]), "revision": 1}

    def list_projects(self, subject: str, is_admin: bool = False) -> list[dict]:
        query = (
            "SELECT p.id, p.slug, p.name, m.role, d.revision, d.updated_at "
            "FROM projects p JOIN protocols d ON d.project_id = p.id "
            "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
        )
        params: tuple = (subject,)
        if not is_admin:
            query += "WHERE m.subject IS NOT NULL "
        query += "ORDER BY p.slug"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [{**row, "id": str(row["id"])} for row in rows]

    def get_protocol(self, slug: str, subject: str, is_admin: bool = False) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT p.id, p.slug, p.name, d.content, d.revision, d.updated_at, m.role "
                "FROM projects p JOIN protocols d ON d.project_id = p.id "
                "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
                "WHERE p.slug = %s",
                (subject, slug),
            ).fetchone()
        if row is None:
            raise ProjectNotFound("project not found")
        if not is_admin and row["role"] is None:
            raise AccessDenied("project access denied")
        return {**row, "id": str(row["id"])}

    def update_protocol(
        self,
        slug: str,
        content: str,
        expected_revision: int,
        actor: str,
        summary: str,
        email: str | None = None,
    ) -> dict:
        validate_protocol(content)
        if not summary.strip() or len(summary) > 500:
            raise ValueError("summary must contain 1-500 characters")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO users (subject, email) VALUES (%s, %s) "
                "ON CONFLICT (subject) DO UPDATE SET email = COALESCE(EXCLUDED.email, users.email)",
                (actor, email),
            )
            project = conn.execute(
                "SELECT p.id, m.role FROM projects p "
                "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
                "WHERE p.slug = %s",
                (actor, slug),
            ).fetchone()
            if project is None:
                raise ProjectNotFound("project not found")
            if project["role"] not in {"owner", "editor"}:
                raise AccessDenied("project edit access denied")
            current = conn.execute(
                "SELECT revision FROM protocols WHERE project_id = %s FOR UPDATE",
                (project["id"],),
            ).fetchone()
            if current is None:
                raise ProjectNotFound("protocol not found")
            if current["revision"] != expected_revision:
                raise RevisionConflict(current["revision"])
            revision = expected_revision + 1
            conn.execute(
                "UPDATE protocols SET content = %s, revision = %s, updated_by = %s, updated_at = now() "
                "WHERE project_id = %s",
                (content, revision, actor, project["id"]),
            )
            conn.execute(
                "INSERT INTO protocol_revisions (project_id, revision, content, actor_subject, summary) "
                "VALUES (%s, %s, %s, %s, %s)",
                (project["id"], revision, content, actor, summary.strip()),
            )
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, revision, details) "
                "VALUES (%s, %s, 'protocol.updated', %s, %s)",
                (project["id"], actor, revision, Jsonb({"summary": summary.strip()})),
            )
        return {"project_slug": slug, "revision": revision}

    def record_approval(
        self,
        slug: str,
        phase_number: int,
        expected_revision: int,
        approved: bool,
        note: str,
        actor: str,
    ) -> dict:
        if phase_number < 1 or len(note) > 2000:
            raise ValueError("invalid phase number or note")
        with self.connect() as conn:
            project = conn.execute(
                "SELECT p.id, m.role FROM projects p "
                "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
                "WHERE p.slug = %s",
                (actor, slug),
            ).fetchone()
            if project is None:
                raise ProjectNotFound("project not found")
            if project["role"] not in {"owner", "editor"}:
                raise AccessDenied("project approval access denied")
            protocol = conn.execute(
                "SELECT revision FROM protocols WHERE project_id = %s FOR UPDATE",
                (project["id"],),
            ).fetchone()
            if protocol is None:
                raise ProjectNotFound("protocol not found")
            if protocol["revision"] != expected_revision:
                raise RevisionConflict(protocol["revision"])
            row = conn.execute(
                "INSERT INTO protocol_approvals "
                "(project_id, phase_number, protocol_revision, actor_subject, approved, note) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
                (project["id"], phase_number, expected_revision, actor, approved, note),
            ).fetchone()
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, revision, details) "
                "VALUES (%s, %s, 'phase.approval', %s, %s)",
                (project["id"], actor, expected_revision,
                 Jsonb({"phase": phase_number, "approved": approved, "note": note})),
            )
        return {"id": row["id"], "created_at": row["created_at"].isoformat()}

    def add_member(self, slug: str, member_subject: str, role: str, actor: str, is_admin: bool = False) -> dict:
        if role not in {"owner", "editor", "reader"}:
            raise ValueError("role must be owner, editor, or reader")
        if not member_subject or len(member_subject) > 512:
            raise ValueError("member subject must contain 1-512 characters")
        with self.connect() as conn:
            conn.execute("INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING", (actor,))
            project = conn.execute(
                "SELECT p.id, m.role FROM projects p "
                "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
                "WHERE p.slug = %s FOR UPDATE OF p",
                (actor, slug),
            ).fetchone()
            if project is None:
                raise ProjectNotFound("project not found")
            if not is_admin and project["role"] != "owner":
                raise AccessDenied("only project owners can manage members")
            conn.execute(
                "INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING",
                (member_subject,),
            )
            conn.execute(
                "INSERT INTO project_memberships (project_id, subject, role) VALUES (%s, %s, %s) "
                "ON CONFLICT (project_id, subject) DO UPDATE SET role = EXCLUDED.role",
                (project["id"], member_subject, role),
            )
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                "VALUES (%s, %s, 'membership.granted', %s)",
                (project["id"], actor, Jsonb({"subject": member_subject, "role": role})),
            )
        return {"project_slug": slug, "subject": member_subject, "role": role}

    def remove_member(self, slug: str, member_subject: str, actor: str, is_admin: bool = False) -> dict:
        if not member_subject or len(member_subject) > 512:
            raise ValueError("member subject must contain 1-512 characters")
        with self.connect() as conn:
            conn.execute("INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING", (actor,))
            project = conn.execute(
                "SELECT p.id, m.role FROM projects p "
                "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s "
                "WHERE p.slug = %s FOR UPDATE OF p",
                (actor, slug),
            ).fetchone()
            if project is None:
                raise ProjectNotFound("project not found")
            if not is_admin and project["role"] != "owner":
                raise AccessDenied("only project owners can manage members")
            member = conn.execute(
                "SELECT role FROM project_memberships WHERE project_id = %s AND subject = %s FOR UPDATE",
                (project["id"], member_subject),
            ).fetchone()
            if member is None:
                raise ProjectNotFound("project member not found")
            if member["role"] == "owner":
                owners = conn.execute(
                    "SELECT count(*) AS count FROM project_memberships "
                    "WHERE project_id = %s AND role = 'owner'",
                    (project["id"],),
                ).fetchone()["count"]
                if owners <= 1:
                    raise ValueError("cannot remove the last project owner")
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                "VALUES (%s, %s, 'membership.revoked', %s)",
                (project["id"], actor, Jsonb({"subject": member_subject, "role": member["role"]})),
            )
            conn.execute(
                "DELETE FROM project_memberships WHERE project_id = %s AND subject = %s",
                (project["id"], member_subject),
            )
        return {"project_slug": slug, "subject": member_subject, "removed": True}

    def list_revisions(self, slug: str, subject: str, limit: int = 20, is_admin: bool = False) -> list[dict]:
        project = self.get_protocol(slug, subject, is_admin)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT r.revision, r.actor_subject, u.email AS actor_email, r.summary, r.created_at "
                "FROM protocol_revisions r LEFT JOIN users u ON u.subject = r.actor_subject WHERE r.project_id = %s "
                "ORDER BY r.revision DESC LIMIT %s",
                (uuid.UUID(project["id"]), min(max(limit, 1), 100)),
            ).fetchall()
        return [{**row, "created_at": row["created_at"].isoformat()} for row in rows]

    def get_revision(self, slug: str, revision: int, subject: str, is_admin: bool = False) -> dict:
        project = self.get_protocol(slug, subject, is_admin)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT r.revision, r.content, r.summary, r.created_at, u.email AS actor_email "
                "FROM protocol_revisions r LEFT JOIN users u ON u.subject = r.actor_subject "
                "WHERE r.project_id = %s AND r.revision = %s",
                (uuid.UUID(project["id"]), revision),
            ).fetchone()
        if row is None:
            raise ProjectNotFound("revision not found")
        return {**row, "created_at": row["created_at"].isoformat(), "slug": slug, "name": project["name"], "role": project["role"]}

    def touch_read(self, slug: str, subject: str, revision: int, via: str) -> None:
        """Remember the latest revision a project member read (agents through MCP, people through the web). Non-members are ignored."""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO protocol_reads (project_id, subject, revision, via) "
                "SELECT p.id, m.subject, %s, %s FROM projects p JOIN project_memberships m ON m.project_id = p.id "
                "WHERE p.slug = %s AND m.subject = %s "
                "ON CONFLICT (project_id, subject) DO UPDATE SET revision = EXCLUDED.revision, via = EXCLUDED.via, read_at = now() "
                "WHERE protocol_reads.revision IS DISTINCT FROM EXCLUDED.revision OR protocol_reads.via IS DISTINCT FROM EXCLUDED.via "
                "OR protocol_reads.read_at < now() - make_interval(secs => %s)",
                (revision, via, slug, subject, READ_REFRESH_SECONDS),
            )

    def sync_status(self, slug: str, subject: str, is_admin: bool = False) -> dict:
        """Per member: has the current protocol revision been read? status is current, behind or never."""
        project = self.get_protocol(slug, subject, is_admin)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT m.subject, u.email, m.role, r.revision, r.via, r.read_at "
                "FROM project_memberships m JOIN users u ON u.subject = m.subject "
                "LEFT JOIN protocol_reads r ON r.project_id = m.project_id AND r.subject = m.subject "
                "WHERE m.project_id = %s ORDER BY lower(u.email)",
                (uuid.UUID(project["id"]),),
            ).fetchall()
        members = []
        for r in rows:
            seen = r["revision"]
            status = "never" if seen is None else "current" if seen >= project["revision"] else "behind"
            members.append({"subject": r["subject"], "email": r["email"], "role": r["role"], "status": status,
                            "read_revision": seen, "behind": 0 if seen is None else max(project["revision"] - seen, 0),
                            "via": r["via"], "read_at": r["read_at"].isoformat() if r["read_at"] else None})
        return {"current_revision": project["revision"], "members": members,
                "synced": sum(1 for m in members if m["status"] == "current"), "total": len(members)}

    def list_members(self, slug: str, subject: str, is_admin: bool = False) -> list[dict]:
        project = self.get_protocol(slug, subject, is_admin)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT m.subject, u.email, m.role, m.created_at "
                "FROM project_memberships m JOIN users u ON u.subject = m.subject "
                "WHERE m.project_id = %s ORDER BY m.role, m.subject",
                (uuid.UUID(project["id"]),),
            ).fetchall()
        return [{**row, "created_at": row["created_at"].isoformat()} for row in rows]

    def list_audit(self, slug: str, subject: str, limit: int = 50, is_admin: bool = False) -> list[dict]:
        project = self.get_protocol(slug, subject, is_admin)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT actor_subject, event_type, revision, details, created_at "
                "FROM audit_events WHERE project_id = %s ORDER BY id DESC LIMIT %s",
                (uuid.UUID(project["id"]), min(max(limit, 1), 100)),
            ).fetchall()
        return [{**row, "created_at": row["created_at"].isoformat()} for row in rows]

    # ---- users, tokens, join ----------------------------------------------

    def create_user(self, email: str, display_name: str, is_admin: bool) -> dict:
        if not is_admin:
            raise AccessDenied("user management requires evidence:admin scope")
        if not email.strip() or len(email) > 320:
            raise ValueError("email must contain 1-320 characters")
        subject = f"local:{uuid.uuid4()}"
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE lower(email) = lower(%s)", (email.strip(),)).fetchone():
                raise ValueError("a user with this email already exists")
            conn.execute(
                "INSERT INTO users (subject, email, display_name) VALUES (%s, %s, %s)",
                (subject, email.strip(), display_name.strip() or None),
            )
        return {"subject": subject, "email": email.strip(), "display_name": display_name.strip()}

    def login_user(self, email: str, display_name: str, allow_create: bool) -> str | None:
        """Subject for a Google-verified email: an existing enabled user, or a new one when allow_create (admin bootstrap)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT subject, disabled FROM users WHERE lower(email) = lower(%s) ORDER BY created_at LIMIT 1",
                (email,),
            ).fetchone()
            if row is not None:
                return None if row["disabled"] else row["subject"]
            if not allow_create:
                return None
            subject = f"local:{uuid.uuid4()}"
            conn.execute("INSERT INTO users (subject, email, display_name) VALUES (%s, %s, %s)",
                         (subject, email, display_name or None))
            return subject

    def list_users(self, is_admin: bool) -> list[dict]:
        if not is_admin:
            raise AccessDenied("user management requires evidence:admin scope")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT subject, email, display_name, disabled, created_at FROM users ORDER BY created_at"
            ).fetchall()
        return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]

    def update_user(self, subject: str, is_admin: bool, display_name: str | None = None,
                    disabled: bool | None = None) -> dict:
        if not is_admin:
            raise AccessDenied("user management requires evidence:admin scope")
        with self.connect() as conn:
            row = conn.execute(
                "UPDATE users SET display_name = COALESCE(%s, display_name), disabled = COALESCE(%s, disabled) "
                "WHERE subject = %s RETURNING subject, email, display_name, disabled",
                (display_name, disabled, subject),
            ).fetchone()
        if row is None:
            raise ProjectNotFound("user not found")
        return row

    def delete_user(self, subject: str, is_admin: bool) -> dict:
        if not is_admin:
            raise AccessDenied("user management requires evidence:admin scope")
        with self.connect() as conn:
            try:
                deleted = conn.execute("DELETE FROM users WHERE subject = %s RETURNING 1", (subject,)).fetchone()
            except psycopg.errors.ForeignKeyViolation:
                raise ValueError("user authored protocol history; disable the user instead") from None
        if deleted is None:
            raise ProjectNotFound("user not found")
        return {"subject": subject, "deleted": True}

    def issue_token(self, subject: str, label: str, is_admin: bool) -> dict:
        """Returns the plaintext token exactly once; only its SHA-256 is stored."""
        if not is_admin:
            raise AccessDenied("token management requires evidence:admin scope")
        token = "evk_" + secrets.token_urlsafe(32)
        token_id = uuid.uuid4()
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE subject = %s", (subject,)).fetchone() is None:
                raise ProjectNotFound("user not found")
            conn.execute(
                "INSERT INTO user_tokens (id, subject, token_hash, label, token_hint) VALUES (%s, %s, %s, %s, %s)",
                (token_id, subject, _hash_token(token), label[:100], token[-8:]),
            )
        return {"id": str(token_id), "subject": subject, "token": token}

    def list_tokens(self, subject: str, is_admin: bool) -> list[dict]:
        if not is_admin:
            raise AccessDenied("token management requires evidence:admin scope")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, label, token_hint, created_at, last_used, revoked_at FROM user_tokens "
                "WHERE subject = %s ORDER BY created_at",
                (subject,),
            ).fetchall()
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else str(v) if k == "id" else v)
                 for k, v in r.items()} for r in rows]

    def revoke_token(self, token_id: str, is_admin: bool) -> dict:
        if not is_admin:
            raise AccessDenied("token management requires evidence:admin scope")
        with self.connect() as conn:
            row = conn.execute(
                "UPDATE user_tokens SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING 1",
                (uuid.UUID(token_id),),
            ).fetchone()
        if row is None:
            raise ProjectNotFound("active token not found")
        return {"id": token_id, "revoked": True}

    def issue_own_token(self, subject: str, label: str) -> dict:
        """A user generates their own Evidence secret (shown once). At most 10 active at a time."""
        with self.connect() as conn:
            user = conn.execute("SELECT disabled FROM users WHERE subject = %s", (subject,)).fetchone()
            if user is None or user["disabled"]:
                raise AccessDenied("user not found or disabled")
            active = conn.execute("SELECT count(*) AS n FROM user_tokens WHERE subject = %s AND revoked_at IS NULL",
                                  (subject,)).fetchone()["n"]
            if active >= 10:
                raise ValueError("you already have 10 active Evidence secrets; revoke one first")
            token, token_id = "evk_" + secrets.token_urlsafe(32), uuid.uuid4()
            conn.execute("INSERT INTO user_tokens (id, subject, token_hash, label, token_hint) VALUES (%s, %s, %s, %s, %s)",
                         (token_id, subject, _hash_token(token), label.strip()[:100], token[-8:]))
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (NULL, %s, 'token.issued', %s)", (subject, Jsonb({"label": label.strip()[:100]})))
        return {"id": str(token_id), "subject": subject, "token": token}

    def list_own_tokens(self, subject: str, recent_revoked: int = 3) -> list[dict]:
        """All active tokens (newest first) plus the most recently revoked few, so the list stays short."""
        everything = self.list_tokens(subject, True)
        active = sorted((t for t in everything if not t["revoked_at"]), key=lambda t: t["created_at"], reverse=True)
        revoked = sorted((t for t in everything if t["revoked_at"]), key=lambda t: t["revoked_at"], reverse=True)
        return active + revoked[:recent_revoked]

    def count_own_revoked(self, subject: str) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT count(*) AS n FROM user_tokens WHERE subject = %s AND revoked_at IS NOT NULL",
                                (subject,)).fetchone()["n"]

    def revoke_own_token(self, token_id: str, subject: str) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "UPDATE user_tokens SET revoked_at = now() WHERE id = %s AND subject = %s AND revoked_at IS NULL RETURNING 1",
                (uuid.UUID(token_id), subject)).fetchone()
            if row is None:
                raise ProjectNotFound("active token not found")
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (NULL, %s, 'token.revoked', '{}')", (subject,))
        return {"id": token_id, "revoked": True}

    def resolve_token(self, token: str) -> dict | None:
        """Subject and email for an active token of an enabled user, else None."""
        if not token.startswith("evk_"):
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT t.id, t.subject, u.email, (t.last_used IS NULL OR t.last_used < now() - make_interval(secs => %s)) AS stale "
                "FROM user_tokens t JOIN users u ON u.subject = t.subject "
                "WHERE t.token_hash = %s AND t.revoked_at IS NULL AND NOT u.disabled",
                (LAST_USED_REFRESH_SECONDS, _hash_token(token)),
            ).fetchone()
            if row is None:
                return None
            if row["stale"]:  # a commit costs far more than the lookup, so refresh last_used at most every few minutes
                conn.execute("UPDATE user_tokens SET last_used = now() WHERE id = %s", (row["id"],))
            return {"subject": row["subject"], "email": row["email"]}

    def join_project(self, subject: str, join_key: str, name: str, initial_content: str) -> dict:
        """Auto-register: create the project (caller becomes owner) or add the caller as editor.

        Idempotent; an existing membership keeps its role.
        """
        join_key = normalize_join_key(join_key)
        if not name.strip() or len(name) > 200:
            raise ValueError("name must contain 1-200 characters")
        for attempt in range(2):  # second pass handles a concurrent creator winning the unique join_key
            with self.connect() as conn:
                conn.execute("INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING", (subject,))
                project = conn.execute(
                    "SELECT id, slug FROM projects WHERE join_key = %s FOR UPDATE", (join_key,)
                ).fetchone()
                if project is not None:
                    inserted = conn.execute(
                        "INSERT INTO project_memberships (project_id, subject, role) VALUES (%s, %s, 'editor') "
                        "ON CONFLICT DO NOTHING RETURNING 1",
                        (project["id"], subject),
                    ).fetchone()
                    role = conn.execute(
                        "SELECT role FROM project_memberships WHERE project_id = %s AND subject = %s",
                        (project["id"], subject),
                    ).fetchone()["role"]
                    if inserted:
                        conn.execute(
                            "INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                            "VALUES (%s, %s, 'membership.granted', %s)",
                            (project["id"], subject, Jsonb({"subject": subject, "role": "editor", "via": "join"})),
                        )
                    return {"project_slug": project["slug"], "role": role, "created": False}
            slug = slug_from_join_key(join_key, suffix=attempt > 0 or self._slug_taken(join_key))
            try:
                created = self.create_project(slug, name, initial_content, subject)
            except psycopg.errors.UniqueViolation:
                continue
            with self.connect() as conn:
                conn.execute("UPDATE projects SET join_key = %s WHERE id = %s", (join_key, created["id"]))
                conn.execute(
                    "INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                    "VALUES (%s, %s, 'project.autocreated', %s)",
                    (created["id"], subject, Jsonb({"join_key": join_key})),
                )
            return {"project_slug": slug, "role": "owner", "created": True}
        raise RuntimeError("could not register project; retry")

    def _slug_taken(self, join_key: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM projects WHERE slug = %s", (slug_from_join_key(join_key),)
            ).fetchone() is not None

    # ---- vault -------------------------------------------------------------

    def list_categories(self) -> list[dict]:
        with self.connect() as conn:
            return conn.execute("SELECT id, name, description FROM secret_categories ORDER BY name").fetchall()

    def create_category(self, name: str, description: str = "") -> dict:
        with self.connect() as conn:
            try:
                return conn.execute(
                    "INSERT INTO secret_categories (name, description) VALUES (%s, %s) RETURNING id, name, description",
                    (name, description),
                ).fetchone()
            except psycopg.errors.CheckViolation:
                raise ValueError("category name must be lowercase letters, digits, or hyphens") from None

    def _vault_project(self, conn, slug: str, actor: str, is_admin: bool, need: str) -> dict:
        """need: 'manage' (owner/admin) or 'read' (any member). Returns project row plus readable category ids."""
        conn.execute("INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING", (actor,))
        project = conn.execute(
            "SELECT p.id, m.role FROM projects p "
            "LEFT JOIN project_memberships m ON m.project_id = p.id AND m.subject = %s WHERE p.slug = %s",
            (actor, slug),
        ).fetchone()
        if project is None:
            raise ProjectNotFound("project not found")
        owner = project["role"] == "owner"
        if need == "manage" and not (owner or is_admin):
            raise AccessDenied("only project owners can manage the vault")
        if need == "read" and project["role"] is None and not is_admin:
            raise AccessDenied("project access denied")
        return {**project, "owner": owner}

    def member_category_names(self, slug: str) -> dict[str, set[str]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT mc.subject, c.name FROM member_categories mc "
                "JOIN secret_categories c ON c.id = mc.category_id "
                "JOIN projects p ON p.id = mc.project_id WHERE p.slug = %s",
                (slug,),
            ).fetchall()
        out: dict[str, set[str]] = {}
        for r in rows:
            out.setdefault(r["subject"], set()).add(r["name"])
        return out

    def set_member_categories(
        self, slug: str, member_subject: str, categories: list[str], actor: str, is_admin: bool = False
    ) -> dict:
        with self.connect() as conn:
            project = self._vault_project(conn, slug, actor, is_admin, "manage")
            if conn.execute(
                "SELECT 1 FROM project_memberships WHERE project_id = %s AND subject = %s",
                (project["id"], member_subject),
            ).fetchone() is None:
                raise ProjectNotFound("project member not found")
            ids = conn.execute(
                "SELECT id FROM secret_categories WHERE name = ANY(%s)", (categories,)
            ).fetchall()
            if len(ids) != len(set(categories)):
                raise ValueError("unknown secret category")
            conn.execute(
                "DELETE FROM member_categories WHERE project_id = %s AND subject = %s",
                (project["id"], member_subject),
            )
            for row in ids:
                conn.execute(
                    "INSERT INTO member_categories (project_id, subject, category_id) VALUES (%s, %s, %s)",
                    (project["id"], member_subject, row["id"]),
                )
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                "VALUES (%s, %s, 'vault.grants_set', %s)",
                (project["id"], actor, Jsonb({"subject": member_subject, "categories": sorted(categories)})),
            )
        return {"project_slug": slug, "subject": member_subject, "categories": sorted(categories)}

    # Secrets are independent vault items. Readable by: their owner, users they are shared with directly,
    # and members of projects they are shared with (project owners read all; other members need the category).

    def _can_read(self, conn, secret: dict, actor: str) -> bool:
        if secret["owner_subject"] == actor:
            return True
        if conn.execute("SELECT 1 FROM secret_user_shares WHERE secret_id = %s AND subject = %s",
                        (secret["id"], actor)).fetchone():
            return True
        return conn.execute(
            "SELECT 1 FROM secret_project_shares sp JOIN project_memberships m "
            "ON m.project_id = sp.project_id AND m.subject = %s "
            "WHERE sp.secret_id = %s AND (m.role = 'owner' OR EXISTS ("
            "SELECT 1 FROM member_categories mc WHERE mc.project_id = sp.project_id AND mc.subject = m.subject "
            "AND mc.category_id = %s))",
            (actor, secret["id"], secret["category_id"]),
        ).fetchone() is not None

    def _manageable_projects(self, conn, actor: str, is_admin: bool) -> dict:
        """slug -> {id, slug, name} for projects the actor may share secrets into."""
        query = ("SELECT p.id, p.slug, p.name FROM projects p " if is_admin else
                 "SELECT p.id, p.slug, p.name FROM projects p JOIN project_memberships m ON m.project_id = p.id "
                 "AND m.subject = %s AND m.role IN ('owner', 'editor') ")
        rows = conn.execute(query + "ORDER BY p.slug", () if is_admin else (actor,)).fetchall()
        return {r["slug"]: r for r in rows}

    def _secret_row(self, conn, name: str, lock: bool = False):
        return conn.execute("SELECT * FROM vault_secrets WHERE name = %s" + (" FOR UPDATE" if lock else ""),
                            (name,)).fetchone()

    def _ensure_user(self, conn, subject: str) -> None:
        conn.execute("INSERT INTO users (subject) VALUES (%s) ON CONFLICT (subject) DO NOTHING", (subject,))

    def vault_put(self, name: str, category: str, value: str, actor: str, is_admin: bool = False,
                  project_slug: str | None = None, description: str | None = None) -> dict:
        """Create a secret you own, or rotate one you own (admins may rotate any). Optionally share it into a project."""
        from method.service import vault_crypto

        if not value or len(value.encode()) > 65_536:
            raise ValueError("secret value must contain 1-65536 bytes")
        if description is not None and len(description) > 500:
            raise ValueError("description must be at most 500 characters")
        with self.connect() as conn:
            self._ensure_user(conn, actor)
            cat = conn.execute("SELECT id FROM secret_categories WHERE name = %s", (category,)).fetchone()
            if cat is None:
                raise ValueError("unknown secret category")
            project = None
            if project_slug:
                project = self._manageable_projects(conn, actor, is_admin).get(project_slug)
                if project is None:
                    raise AccessDenied("you can only share into projects you own or edit")
            existing = self._secret_row(conn, name, lock=True)
            if existing is not None and existing["owner_subject"] != actor and not is_admin:
                raise AccessDenied("a secret with this name already exists and belongs to someone else")
            secret_id = existing["id"] if existing else uuid.uuid4()
            nonce, blob = vault_crypto.encrypt(value, str(secret_id))
            try:
                if existing:
                    row = conn.execute(
                        "UPDATE vault_secrets SET category_id = %s, nonce = %s, ciphertext = %s, key_version = %s, "
                        "revision = revision + 1, updated_by = %s, updated_at = now(), "
                        "description = COALESCE(%s, description) WHERE id = %s RETURNING revision",
                        (cat["id"], nonce, blob, vault_crypto.KEY_VERSION, actor, description, secret_id)).fetchone()
                else:
                    row = conn.execute(
                        "INSERT INTO vault_secrets (id, project_id, category_id, name, nonce, ciphertext, key_version, "
                        "updated_by, owner_subject, description) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING revision",
                        (secret_id, cat["id"], name, nonce, blob, vault_crypto.KEY_VERSION, actor, actor,
                         (description or "").strip())).fetchone()
            except psycopg.errors.CheckViolation:
                raise ValueError("secret name must match [A-Za-z_][A-Za-z0-9_]{0,127}") from None
            if project:
                conn.execute("INSERT INTO secret_project_shares (secret_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                             (secret_id, project["id"]))
            conn.execute(
                "INSERT INTO audit_events (project_id, actor_subject, event_type, details) VALUES (%s, %s, 'vault.put', %s)",
                (project["id"] if project else None, actor,
                 Jsonb({"name": name, "category": category, "revision": row["revision"], "created": existing is None})))
        return {"name": name, "category": category, "revision": row["revision"], "created": existing is None}

    def secret_exists(self, name: str) -> bool:
        with self.connect() as conn:
            return self._secret_row(conn, name) is not None

    def vault_update(self, name: str, actor: str, is_admin: bool = False, category: str | None = None,
                     description: str | None = None, value: str | None = None) -> dict:
        """Change a secret's details; the value only changes when a new one is given."""
        from method.service import vault_crypto

        if description is not None and len(description) > 500:
            raise ValueError("description must be at most 500 characters")
        if value is not None and (not value or len(value.encode()) > 65_536):
            raise ValueError("secret value must contain 1-65536 bytes")
        with self.connect() as conn:
            sec = self._secret_row(conn, name, lock=True)
            if sec is None or (sec["owner_subject"] != actor and not is_admin):
                raise AccessDenied("secret not found or you are not its owner")
            cat_id = sec["category_id"]
            if category is not None:
                cat = conn.execute("SELECT id FROM secret_categories WHERE name = %s", (category,)).fetchone()
                if cat is None:
                    raise ValueError("unknown secret category")
                cat_id = cat["id"]
            fields, params = ["category_id = %s", "updated_by = %s", "updated_at = now()", "description = %s"], [
                cat_id, actor, sec["description"] if description is None else description.strip()]
            if value is not None:
                nonce, blob = vault_crypto.encrypt(value, str(sec["id"]))
                fields += ["nonce = %s", "ciphertext = %s", "key_version = %s", "revision = revision + 1"]
                params += [nonce, blob, vault_crypto.KEY_VERSION]
            row = conn.execute(f"UPDATE vault_secrets SET {', '.join(fields)} WHERE id = %s RETURNING revision",
                               (*params, sec["id"])).fetchone()
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (NULL, %s, 'vault.updated', %s)",
                         (actor, Jsonb({"name": name, "value_changed": value is not None, "revision": row["revision"]})))
        return {"name": name, "revision": row["revision"], "value_changed": value is not None}

    def vault_list(self, actor: str, is_admin: bool = False, project_slug: str | None = None,
                   include_unreadable: bool = False) -> list[dict]:
        """Metadata only, never values. Normally just what the actor can read; admins may include everything."""
        with self.connect() as conn:
            project_id = None
            if project_slug:
                project = conn.execute("SELECT id FROM projects WHERE slug = %s", (project_slug,)).fetchone()
                if project is None:
                    raise ProjectNotFound("project not found")
                project_id = project["id"]
            secrets_ = conn.execute(
                "SELECT s.id, s.name, s.category_id, c.name AS category, s.owner_subject, u.email AS owner_email, "
                "s.revision, s.updated_at, s.description FROM vault_secrets s JOIN secret_categories c ON c.id = s.category_id "
                "LEFT JOIN users u ON u.subject = s.owner_subject ORDER BY s.name").fetchall()
            out = []
            for sec in secrets_:
                readable = self._can_read(conn, sec, actor)
                shared_projects = [r["slug"] for r in conn.execute(
                    "SELECT p.slug FROM secret_project_shares sp JOIN projects p ON p.id = sp.project_id "
                    "WHERE sp.secret_id = %s ORDER BY p.slug", (sec["id"],)).fetchall()]
                if project_slug and project_slug not in shared_projects:
                    continue
                if not (readable or (include_unreadable and is_admin)):
                    continue
                users = conn.execute("SELECT count(*) AS n FROM secret_user_shares WHERE secret_id = %s",
                                     (sec["id"],)).fetchone()["n"]
                out.append({"name": sec["name"], "category": sec["category"], "revision": sec["revision"],
                            "description": sec["description"],
                            "owner": sec["owner_email"] or sec["owner_subject"], "mine": sec["owner_subject"] == actor,
                            "projects": shared_projects, "users": users, "readable": readable,
                            "updated_at": sec["updated_at"].isoformat()})
        return out

    def vault_get(self, name: str, actor: str, project_slug: str | None = None) -> str:
        """Decrypt one secret the actor can read; audited. Admin scope does not bypass sharing."""
        from method.service import vault_crypto

        with self.connect() as conn:
            project_id = None
            if project_slug:
                project = conn.execute("SELECT id FROM projects WHERE slug = %s", (project_slug,)).fetchone()
                project_id = project["id"] if project else None
                if project is None:
                    raise AccessDenied("secret not found or not shared with you")
            sec = self._secret_row(conn, name)
            in_scope = sec is not None and (project_id is None or conn.execute(
                "SELECT 1 FROM secret_project_shares WHERE secret_id = %s AND project_id = %s",
                (sec["id"], project_id)).fetchone() is not None)
            if not in_scope or not self._can_read(conn, sec, actor):
                raise AccessDenied("secret not found or not shared with you")  # same error: no existence oracle
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (%s, %s, 'vault.read', %s)", (project_id, actor, Jsonb({"name": name})))
            return vault_crypto.decrypt(sec["nonce"], sec["ciphertext"], str(sec["id"]))

    def vault_delete(self, name: str, actor: str, is_admin: bool = False) -> dict:
        with self.connect() as conn:
            sec = self._secret_row(conn, name, lock=True)
            if sec is None:
                raise ProjectNotFound("secret not found")
            if sec["owner_subject"] != actor and not is_admin:
                raise AccessDenied("only the owner can delete a secret")
            conn.execute("DELETE FROM vault_secrets WHERE id = %s", (sec["id"],))
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (NULL, %s, 'vault.deleted', %s)", (actor, Jsonb({"name": name})))
        return {"name": name, "deleted": True}

    def list_people(self, actor: str) -> list[dict]:
        """Other active users (for sharing pickers)."""
        with self.connect() as conn:
            return conn.execute("SELECT subject, email, display_name FROM users WHERE NOT disabled AND email IS NOT NULL "
                                "AND subject <> %s ORDER BY lower(email)", (actor,)).fetchall()

    def list_manageable_projects(self, actor: str, is_admin: bool = False) -> list[dict]:
        with self.connect() as conn:
            return [{"slug": p["slug"], "name": p["name"]} for p in self._manageable_projects(conn, actor, is_admin).values()]

    def subjects_for_emails(self, emails: list[str]) -> list[str]:
        if not emails:
            return []
        with self.connect() as conn:
            rows = conn.execute("SELECT subject, lower(email) AS email FROM users WHERE lower(email) = ANY(%s) AND NOT disabled",
                                ([e.strip().lower() for e in emails],)).fetchall()
        missing = {e.strip().lower() for e in emails} - {r["email"] for r in rows}
        if missing:
            raise ValueError(f"unknown or disabled users: {', '.join(sorted(missing))}")
        return [r["subject"] for r in rows]

    def secret_shares(self, name: str, actor: str, is_admin: bool = False) -> dict:
        """Current shares plus what the actor may add; owner or admin only."""
        with self.connect() as conn:
            sec = self._secret_row(conn, name)
            if sec is None or (sec["owner_subject"] != actor and not is_admin):
                raise AccessDenied("secret not found or you are not its owner")
            category = conn.execute("SELECT name FROM secret_categories WHERE id = %s", (sec["category_id"],)).fetchone()["name"]
            projects = [r["slug"] for r in conn.execute(
                "SELECT p.slug FROM secret_project_shares sp JOIN projects p ON p.id = sp.project_id "
                "WHERE sp.secret_id = %s", (sec["id"],)).fetchall()]
            users = [r["subject"] for r in conn.execute(
                "SELECT subject FROM secret_user_shares WHERE secret_id = %s", (sec["id"],)).fetchall()]
            manageable = [{"slug": p["slug"], "name": p["name"]} for p in self._manageable_projects(conn, actor, is_admin).values()]
            people = conn.execute("SELECT subject, email, display_name FROM users WHERE NOT disabled AND email IS NOT NULL "
                                  "AND subject <> %s ORDER BY lower(email)", (sec["owner_subject"],)).fetchall()
        return {"name": name, "category": category, "description": sec["description"], "projects": projects, "users": users, "manageable_projects": manageable,
                "people": people, "owner": sec["owner_subject"]}

    def set_secret_shares(self, name: str, project_slugs: list[str], user_subjects: list[str], actor: str,
                          is_admin: bool = False) -> dict:
        """Replace who a secret is shared with. Projects outside the actor's reach are left untouched."""
        with self.connect() as conn:
            sec = self._secret_row(conn, name, lock=True)
            if sec is None or (sec["owner_subject"] != actor and not is_admin):
                raise AccessDenied("secret not found or you are not its owner")
            manageable = self._manageable_projects(conn, actor, is_admin)
            wanted = set(project_slugs)
            outside = wanted - set(manageable)
            if outside:
                raise AccessDenied("you can only share into projects you own or edit")
            managed_ids = [p["id"] for p in manageable.values()]
            conn.execute("DELETE FROM secret_project_shares WHERE secret_id = %s AND project_id = ANY(%s)",
                         (sec["id"], managed_ids))
            for slug in wanted:
                conn.execute("INSERT INTO secret_project_shares (secret_id, project_id) VALUES (%s, %s)",
                             (sec["id"], manageable[slug]["id"]))
            valid = {r["subject"] for r in conn.execute(
                "SELECT subject FROM users WHERE subject = ANY(%s) AND NOT disabled AND subject <> %s",
                (list(user_subjects), sec["owner_subject"])).fetchall()}
            if valid != set(user_subjects) - {sec["owner_subject"]}:
                raise ValueError("unknown or disabled user in share list")
            conn.execute("DELETE FROM secret_user_shares WHERE secret_id = %s", (sec["id"],))
            for subject in valid:
                conn.execute("INSERT INTO secret_user_shares (secret_id, subject) VALUES (%s, %s)", (sec["id"], subject))
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (NULL, %s, 'vault.shared', %s)",
                         (actor, Jsonb({"name": name, "projects": sorted(wanted), "users": len(valid)})))
        return {"name": name, "projects": sorted(wanted), "users": len(valid)}

    def unshare_from_project(self, name: str, project_slug: str, actor: str, is_admin: bool = False) -> dict:
        with self.connect() as conn:
            sec = self._secret_row(conn, name, lock=True)
            project = self._manageable_projects(conn, actor, is_admin).get(project_slug)
            if sec is None or project is None or (sec["owner_subject"] != actor and not is_admin):
                raise AccessDenied("secret or project not found, or not yours to change")
            conn.execute("DELETE FROM secret_project_shares WHERE secret_id = %s AND project_id = %s", (sec["id"], project["id"]))
            conn.execute("INSERT INTO audit_events (project_id, actor_subject, event_type, details) "
                         "VALUES (%s, %s, 'vault.unshared', %s)", (project["id"], actor, Jsonb({"name": name})))
        return {"name": name, "project_slug": project_slug, "unshared": True}

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_join_key(value: str) -> str:
    """git remote (ssh or https) or any identifier -> lowercase host/path without credentials or .git."""
    key = value.strip().lower()
    key = re.sub(r"^[a-z+]+://", "", key)
    key = re.sub(r"^[^@/]*@", "", key)  # drop user[:password]@
    key = key.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]", key) else key
    key = re.sub(r"\.git$", "", key.strip("/"))
    if not re.fullmatch(r"[a-z0-9._/-]{3,200}", key):
        raise ValueError("join key must be a repository identifier such as host/org/repo")
    return key


def slug_from_join_key(join_key: str, suffix: bool = False) -> str:
    parts = join_key.split("/")[1:] or join_key.split("/")  # drop host
    base = re.sub(r"[^a-z0-9]+", "-", "-".join(parts)).strip("-")[:56] or "project"
    if suffix:
        base = f"{base[:56]}-{hashlib.sha256(join_key.encode()).hexdigest()[:6]}"
    return base if len(base) >= 3 else base + "-prj"


def validate_protocol(content: str) -> None:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("protocol content must be a non-empty string")
    if len(content.encode("utf-8")) > MAX_PROTOCOL_BYTES:
        raise ValueError(f"protocol content exceeds {MAX_PROTOCOL_BYTES} bytes")
