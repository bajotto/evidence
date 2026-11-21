from __future__ import annotations

import base64
import os
import re
import unittest
import uuid
from unittest.mock import patch

from starlette.testclient import TestClient

from method.service.remote_mcp_server import create_server
from method.service.store import Store
from method.service.ui import sign

CONNINFO = os.environ.get("EVIDENCE_TEST_CONNINFO")
SECRET = "x" * 40
ENV = {
    "MCP_OIDC_ISSUER_URL": "https://issuer.example", "MCP_OIDC_AUDIENCE": "evidence-mcp",
    "MCP_PUBLIC_URL": "https://mcp.example.test/mcp", "MCP_ALLOWED_HOSTS": "testserver",
    "UI_SESSION_SECRET": SECRET, "GOOGLE_CLIENT_ID": "test-client.apps.example", "GOOGLE_CLIENT_SECRET": "test-secret",
    "ADMIN_EMAILS": "boss@example.test",
    "VAULT_MASTER_KEY": base64.b64encode(os.urandom(32)).decode(),
}


class _NoVerify:
    async def verify_token(self, token):
        return None


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class AdminUiTests(unittest.TestCase):
    def setUp(self):
        import time
        self.store = Store(CONNINFO)
        self.store.initialize()
        patcher = patch.dict(os.environ, ENV)  # must outlive create_server: the vault reads its key per request
        patcher.start()
        self.addCleanup(patcher.stop)
        app = create_server(self.store, _NoVerify()).streamable_http_app()
        self.client = TestClient(app, base_url="https://testserver", follow_redirects=False)
        self.sfx = uuid.uuid4().hex[:8]
        self.admin = f"ui-admin-{self.sfx}"
        self.csrf = "csrf-token-" + self.sfx
        exp = time.time() + 600
        self.admin_cookie = sign(SECRET, {"sub": self.admin, "email": "boss@example.test", "admin": True, "csrf": self.csrf, "exp": exp})
        self.user_cookie = sign(SECRET, {"sub": "plain", "email": "p@example.test", "admin": False, "csrf": "c", "exp": exp})
        self.slug = f"ui-{self.sfx}"

    def tearDown(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM projects WHERE slug = %s", (self.slug,))
            conn.execute("DELETE FROM vault_secrets WHERE owner_subject = %s OR updated_by = %s", (self.admin, self.admin))
            conn.execute("DELETE FROM audit_events WHERE actor_subject = %s OR actor_subject IN "
                         "(SELECT subject FROM users WHERE email LIKE %s)", (self.admin, f"%{self.sfx}@ui.test"))
            conn.execute("DELETE FROM users WHERE subject = %s OR email LIKE %s", (self.admin, f"%{self.sfx}@ui.test"))

    def post(self, path, data, cookie=None, csrf=True):
        self.client.cookies.clear()
        self.client.cookies.set("evui", cookie or self.admin_cookie, path="/ui")
        return self.client.post(path, data={**data, **({"csrf": self.csrf} if csrf else {})})

    def test_root_sends_visitors_to_the_secrets_page(self):
        self.client.cookies.clear()
        for path in ("/", "/ui"):
            self.assertEqual(self.client.get(path).headers["location"], "/ui/vault", path)
        self.assertEqual(self.client.get("/ui/vault").headers["location"], "/ui/login")  # then the login page

    def test_login_page_has_only_logo_and_google_button(self):
        self.client.cookies.clear()
        page = self.client.get("/ui/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/ui/static/logo.png", page.text)
        self.assertIn("Sign in with Google", page.text)
        self.assertIn("/ui/login/google", page.text)
        for forbidden in ("<form", "<input", "password", "Users</a>"):
            self.assertNotIn(forbidden, page.text, forbidden)
        self.assertIn("not authorised", self.client.get("/ui/login?e=denied").text)
        self.assertNotIn("not authorised", page.text)
        csp = page.headers["content-security-policy"]
        self.assertIn("style-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        self.assertEqual(self.client.get("/ui/login").headers["location"], "/ui/vault")  # already signed in

    def test_signed_in_email_is_shown_and_protected_from_cloudflare_obfuscation(self):
        self.client.cookies.clear()
        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        html = self.client.get("/ui/vault").text
        self.assertIn("<!--email_off-->boss@example.test<!--/email_off-->", html)
        self.assertIn("<mark>admin</mark>", html)
        self.assertIn("Log out", html)
        self.client.cookies.set("evui", self.user_cookie, path="/ui")
        html = self.client.get("/ui/vault").text
        self.assertIn("<!--email_off-->p@example.test<!--/email_off-->", html)
        self.assertIn("<mark>member</mark>", html)
        self.assertNotIn("/ui/users", html)

    def test_asset_urls_are_versioned_so_a_cdn_never_serves_stale_css(self):
        import re as _re
        self.client.cookies.clear()
        html = self.client.get("/ui/login").text
        refs = _re.findall(r"/ui/static/([a-z.]+)\?v=([0-9a-f]{10})", html)
        self.assertEqual({n for n, _ in refs}, {"icon.png", "pico.min.css", "app.css", "logo.png"})
        self.assertEqual(len({v for _, v in refs}), 1)  # one content hash for the whole static set
        self.assertEqual(self.client.get(f"/ui/static/app.css?v={refs[0][1]}").status_code, 200)

    def test_static_files_are_whitelisted(self):
        for name, kind in (("pico.min.css", "text/css"), ("app.css", "text/css"), ("logo.png", "image/png"), ("icon.png", "image/png")):
            r = self.client.get(f"/ui/static/{name}")
            self.assertEqual((r.status_code, r.headers["content-type"].split(";")[0]), (200, kind), name)
        for name in ("ui.py", "..%2Fui.py", "store.py", "app.css.map"):
            self.assertEqual(self.client.get(f"/ui/static/{name}").status_code, 404, name)

    def test_new_secret_form_has_multiline_value_description_and_sharing_pickers(self):
        self.post("/ui/projects", {"slug": self.slug, "name": "Pick me"})
        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        html = self.client.get(f"/ui/secret/new?project={self.slug}").text
        self.assertIn("<textarea", html)
        self.assertIn("name='value'", html)
        self.assertIn("rows='10'", html)
        self.assertIn("name='description'", html)
        self.assertIn("data-mask='secret-value'", html)  # hide-while-typing toggle
        self.assertIn(f"value='{self.slug}' checked", html)  # preselected from the project page
        self.assertIn("pattern='[A-Za-z_][A-Za-z0-9_]*'", html)
        self.assertIn("Create secret", html)

    def test_multiline_values_keep_their_lines_even_with_browser_crlf(self):
        name, single = f"PEM{self.sfx}", f"ONE{self.sfx}"
        key = "-----BEGIN KEY-----\r\nabc123\r\n-----END KEY-----\r\n"
        self.assertEqual(self.post("/ui/vault/save", {"name": name, "category": "credentials", "value": key,
                                                     "description": "deploy key"}).status_code, 303)
        self.post("/ui/vault/save", {"name": single, "category": "env", "value": "  just-one-line \r\n"})
        got = self.client.post("/ui/vault/value", data={"csrf": self.csrf, "name": name}).json()["value"]
        self.assertEqual(got, "-----BEGIN KEY-----\nabc123\n-----END KEY-----\n")  # LF, no CR, lines intact
        self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": self.csrf, "name": single}).json()["value"], "just-one-line")
        page = self.client.get("/ui/vault").text
        self.assertIn("deploy key", page)  # the description is shown, the value is not
        self.assertNotIn("abc123", page)

    def test_duplicate_name_is_refused_with_a_clear_message(self):
        name = f"DUP{self.sfx}"
        self.post("/ui/vault/save", {"name": name, "category": "env", "value": "one"})
        again = self.post("/ui/vault/save", {"name": name, "category": "env", "value": "two"})
        self.assertEqual(again.status_code, 400)
        self.assertIn("already exists", again.text)
        self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": self.csrf, "name": name}).json()["value"], "one")

    def test_manage_page_edits_details_without_the_value_and_rotates_only_when_given(self):
        name = f"EDIT{self.sfx}"
        self.post("/ui/vault/save", {"name": name, "category": "env", "value": "original", "description": "old"})
        done = self.post("/ui/secret/update", {"name": name, "category": "infra", "description": "new text", "value": ""})
        self.assertEqual(done.headers["location"], f"/ui/secret?name={name}&msg=saved")
        self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": self.csrf, "name": name}).json()["value"], "original")
        html = self.client.get(f"/ui/secret?name={name}&msg=saved").text
        self.assertIn("Changes saved.", html)
        self.assertIn("new text", html)
        self.assertIn("<option value='infra' selected>", html)
        self.assertIn("data-confirm=", html)  # delete asks first
        self.post("/ui/secret/update", {"name": name, "category": "infra", "description": "new text", "value": "line1\r\nline2"})
        self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": self.csrf, "name": name}).json()["value"], "line1\nline2\n")

    def test_secrets_page_search_empty_state_and_active_navigation(self):
        self.client.cookies.clear()
        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        empty = self.client.get("/ui/vault").text
        self.assertIn("No secrets yet", empty)
        self.assertIn("Add your first secret", empty)
        self.assertNotIn("id='q'", empty)
        self.post("/ui/vault/save", {"name": f"FIND{self.sfx}", "category": "api-keys", "value": "v", "description": "billing key"})
        html = self.client.get("/ui/vault").text
        self.assertIn("id='q'", html)  # search appears once there is something to search
        self.assertIn(f"data-search='find{self.sfx.lower()} billing key api-keys", html)
        self.assertIn("aria-current=page>Secrets<", html)
        self.assertIn("<h1>Secrets</h1>", html)
        self.assertIn("+ New secret", html)

    def test_members_read_and_download_the_protocol_and_only_editors_edit_it(self):
        self.post("/ui/projects", {"slug": self.slug, "name": "Doc project"})
        reader = self.store.create_user(f"rd{self.sfx}@ui.test", "Reader", True)["subject"]
        editor = self.store.create_user(f"ed{self.sfx}@ui.test", "Editor", True)["subject"]
        outsider = self.store.create_user(f"out{self.sfx}@ui.test", "Out", True)["subject"]
        self.store.add_member(self.slug, reader, "reader", self.admin, True)
        self.store.add_member(self.slug, editor, "editor", self.admin, True)
        hostile = "# Phase 4\n\nBody <script>alert(1)</script> and **bold**.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.store.update_protocol(self.slug, hostile, 1, self.admin, "add content")
        q = f"slug={self.slug}"
        try:
            self.as_user(self.member_cookie(reader, f"rd{self.sfx}@ui.test", "rc"))
            plist = self.client.get("/ui/projects").text
            self.assertIn("Doc project", plist)
            self.assertNotIn("+ New project", plist)  # members cannot create projects here
            view = self.client.get(f"/ui/protocol?{q}")
            self.assertEqual(view.status_code, 200)
            self.assertIn("<h2 id='phase-4'>Phase 4</h2>", view.text)
            self.assertIn("<strong>bold</strong>", view.text)
            self.assertIn("<th>a</th>", view.text)
            self.assertNotIn("<script>alert", view.text)  # escaped, never executed
            self.assertIn("&lt;script&gt;", view.text)
            self.assertNotIn(f"/ui/protocol/edit?{q}", view.text)  # no Edit for readers
            raw = self.client.get(f"/ui/protocol/raw?{q}")
            self.assertEqual(raw.text, hostile)
            self.assertIn("attachment", raw.headers["content-disposition"])
            self.assertIn("EVIDENCE_PROTOCOL.md", raw.headers["content-disposition"])
            self.assertEqual(self.client.get(f"/ui/protocol/edit?{q}").status_code, 403)
            self.assertEqual(self.client.post("/ui/protocol/save", data={"csrf": "rc", "slug": self.slug, "expected_revision": "2",
                                                                          "summary": "x", "content": "# hacked"}).status_code, 403)
            self.as_user(self.member_cookie(outsider, f"out{self.sfx}@ui.test", "oc"))
            self.assertEqual(self.client.get(f"/ui/protocol?{q}").status_code, 403)
            self.assertEqual(self.client.get(f"/ui/protocol/raw?{q}").status_code, 403)

            self.as_user(self.member_cookie(editor, f"ed{self.sfx}@ui.test", "ec"))
            self.assertIn(f"/ui/protocol/edit?{q}", self.client.get(f"/ui/protocol?{q}").text)
            form = self.client.get(f"/ui/protocol/edit?{q}").text
            self.assertIn("<textarea", form)
            self.assertIn("name='expected_revision' value='2'", form)
            saved = self.client.post("/ui/protocol/save", data={"csrf": "ec", "slug": self.slug, "expected_revision": "2",
                                                                "summary": "edited in the app", "content": "# Phase 5\r\n\r\nNew text\r\n"})
            self.assertEqual(saved.headers["location"], f"/ui/protocol?{q}&msg=protocol-saved")
            current = self.store.get_protocol(self.slug, editor)
            self.assertEqual(current["revision"], 3)
            self.assertIn("New text", current["content"])
            self.assertIn("PROTOCOL-HEADER:START", current["content"])  # header regenerated like the MCP tool does
            self.assertNotIn("\r", current["content"])
            self.assertIn("Protocol saved as a new revision.", self.client.get(f"/ui/protocol?{q}&msg=protocol-saved").text)

            stale = self.client.post("/ui/protocol/save", data={"csrf": "ec", "slug": self.slug, "expected_revision": "2",
                                                                "summary": "late", "content": "# my work in progress"})
            self.assertEqual(stale.status_code, 200)
            self.assertIn("saved by someone else", stale.text)
            self.assertIn("my work in progress", stale.text)  # the text is kept, nothing is lost
            self.assertEqual(self.store.get_protocol(self.slug, editor)["revision"], 3)  # and nothing was overwritten

            hist = self.client.get(f"/ui/protocol/history?{q}").text
            self.assertIn("edited in the app", hist)
            self.assertIn("revision 3", hist)
            old = self.client.get(f"/ui/protocol?{q}&rev=2").text
            self.assertIn("You are reading revision 2", old)
            self.assertIn("<h2 id='phase-4'>Phase 4</h2>", old)
            self.assertEqual(self.client.get(f"/ui/protocol/raw?{q}&rev=2").text, hostile)
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM projects WHERE slug = %s", (self.slug,))
                conn.execute("DELETE FROM audit_events WHERE actor_subject = ANY(%s)", ([reader, editor, outsider],))
                conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([reader, editor, outsider],))

    def test_protocol_page_shows_who_is_in_sync_and_the_label_is_explained(self):
        self.post("/ui/projects", {"slug": self.slug, "name": "Sync project"})
        a = self.store.create_user(f"sa{self.sfx}@ui.test", "A", True)["subject"]
        b = self.store.create_user(f"sb{self.sfx}@ui.test", "B", True)["subject"]
        self.store.add_member(self.slug, a, "reader", self.admin, True)
        self.store.add_member(self.slug, b, "reader", self.admin, True)
        try:
            self.as_user(self.member_cookie(a, f"sa{self.sfx}@ui.test", "ac"))
            html = self.client.get(f"/ui/protocol?slug={self.slug}").text  # opening it counts as a read
            self.assertIn("Sync status:", html)
            self.assertIn("never read", html)  # b, and the admin owner, have not read it
            self.assertIn("up to date", html)  # a just did
            self.assertIn("class='sync attention'", html)  # not everyone is in sync, so it is highlighted
            self.store.update_protocol(self.slug, "# newer\n", 1, self.admin, "second revision")
            self.as_user(self.admin_cookie)
            admin_html = self.client.get(f"/ui/project?slug={self.slug}").text  # the management page shows it per member
            self.assertIn("1 behind", admin_html)
            self.assertIn("never read", admin_html)
            users_html = self.client.get("/ui/users").text
            self.assertNotIn("name=label", users_html)  # admins issue keys without any label field
            self.assertNotIn("placeholder=label", users_html)
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM projects WHERE slug = %s", (self.slug,))
                conn.execute("DELETE FROM audit_events WHERE actor_subject = ANY(%s)", ([a, b],))
                conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([a, b],))

    def test_evidence_secret_page_carries_the_copy_paste_prompt_without_any_secret(self):
        u = self.store.create_user(f"pr{self.sfx}@ui.test", "Prompt", True)
        try:
            self.as_user(self.member_cookie(u["subject"], u["email"], "pc"))
            html = self.client.get("/ui/token").text
            self.assertIn("Add a project to Evidence", html)
            self.assertIn("data-copy='agent-prompt'", html)
            self.assertIn("curl -fsSL https://mcp.example.test/install.py", html)
            self.assertIn("--service-url https://mcp.example.test/mcp", html)
            self.assertIn("EVIDENCE_TOKEN", html)
            self.assertIn("Never print it", html)
            self.assertNotIn("evk_", html.replace("evk_&hellip;", ""))  # the prompt carries no key, only the variable name
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM users WHERE subject = %s", (u["subject"],))

    def test_hook_endpoint_returns_the_current_header_and_records_a_hook_read(self):
        a = self.store.create_user(f"hk{self.sfx}@ui.test", "Hook", True)["subject"]
        out = self.store.create_user(f"ho{self.sfx}@ui.test", "Outsider", True)["subject"]
        ta, to = (self.store.issue_own_token(x, "cli")["token"] for x in (a, out))
        key = f"git.example/org/hook-{self.sfx}"
        slug = None
        with patch.dict(os.environ):  # no OIDC issuer: per-user keys only, verified by the real composite verifier
            os.environ.pop("MCP_OIDC_ISSUER_URL", None)
            real = TestClient(create_server(self.store, None).streamable_http_app(), base_url="https://testserver", follow_redirects=False)
        try:
            made = self.client.post("/api/join", headers={"Authorization": f"Bearer {ta}"},
                                    json={"join_key": key, "name": "Hook", "protocol": "# Hook project\n\nBody.\n"})
            slug = made.json()["project_slug"]
            ok = real.get(f"/api/protocol/header?project={slug}", headers={"Authorization": f"Bearer {ta}"})
            self.assertEqual(ok.status_code, 200)
            body = ok.json()
            self.assertEqual((body["revision"], body["project_slug"]), (1, slug))
            self.assertIn("PROTOCOL HEADER", body["header"])
            self.assertEqual(ok.headers["cache-control"], "no-store")
            seen = self.store.sync_status(slug, a)["members"][0]
            self.assertEqual((seen["status"], seen["via"]), ("current", "hook"))
            self.assertEqual(real.get(f"/api/protocol/header?project={slug}", headers={"Authorization": f"Bearer {to}"}).status_code, 403)
            self.assertEqual(real.get(f"/api/protocol/header?project={slug}").status_code, 401)
            self.assertEqual(real.get(f"/api/protocol/header?project={slug}", headers={"Authorization": "Bearer evk_wrong"}).status_code, 401)
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM projects WHERE join_key = %s", (key.lower(),))
                conn.execute("DELETE FROM audit_events WHERE actor_subject = ANY(%s)", ([a, out],))
                conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([a, out],))

    def test_installer_is_served_and_join_imports_a_local_protocol_only_for_new_projects(self):
        installer = self.client.get("/install.py")
        self.assertEqual(installer.status_code, 200)
        self.assertIn("def main", installer.text)
        self.assertIn("reject_standalone_guidance", installer.text)
        a = self.store.create_user(f"ja{self.sfx}@ui.test", "A", True)["subject"]
        b = self.store.create_user(f"jb{self.sfx}@ui.test", "B", True)["subject"]
        ta, tb = (self.store.issue_own_token(x, "cli")["token"] for x in (a, b))
        key = f"git.example/org/imp-{self.sfx}"
        slug = None
        try:
            first = self.client.post("/api/join", headers={"Authorization": f"Bearer {ta}"},
                                     json={"join_key": key, "name": "Imp", "protocol": "# Existing protocol\n\nImported body marker.\n"})
            self.assertEqual(first.status_code, 200)
            body = first.json()
            slug = body["project_slug"]
            self.assertEqual((body["created"], body["imported_protocol"], body["role"]), (True, True, "owner"))
            self.assertIn("Imported body marker.", self.store.get_protocol(slug, a)["content"])
            second = self.client.post("/api/join", headers={"Authorization": f"Bearer {tb}"},
                                      json={"join_key": key, "name": "Imp", "protocol": "# A different local file\n"})
            self.assertEqual((second.json()["created"], second.json()["imported_protocol"], second.json()["role"]), (False, False, "editor"))
            self.assertIn("Imported body marker.", self.store.get_protocol(slug, b)["content"])  # central copy wins
            self.assertEqual(self.client.post("/api/join", headers={"Authorization": f"Bearer {ta}"}, json={"join_key": key, "protocol": 5}).status_code, 400)
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM projects WHERE join_key = %s", (key.lower(),))
                conn.execute("DELETE FROM audit_events WHERE actor_subject = ANY(%s)", ([a, b],))
                conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([a, b],))

    def test_destructive_actions_ask_for_confirmation(self):
        self.post("/ui/users", {"email": f"del{self.sfx}@ui.test", "display_name": "Del"})
        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        html = self.client.get("/ui/users").text
        self.assertIn("data-confirm='Delete this user?", html)
        self.assertIn("+ New user", html)  # creation is tucked into a collapsible form

    def test_requires_admin_session_and_csrf(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/ui/users").headers["location"], "/ui/login")
        self.client.cookies.set("evui", self.user_cookie, path="/ui")
        self.assertEqual(self.client.get("/ui/users").headers["location"], "/ui/vault")  # non-admin: no admin pages
        self.client.cookies.set("evui", "tampered." + self.admin_cookie.split(".")[1], path="/ui")
        self.assertEqual(self.client.get("/ui/users").status_code, 303)
        self.assertEqual(self.post("/ui/users", {"email": f"a{self.sfx}@ui.test"}, csrf=False).status_code, 403)

    def member_cookie(self, subject, email, csrf="mcsrf"):
        import time
        return sign(SECRET, {"sub": subject, "email": email, "admin": False, "csrf": csrf, "exp": time.time() + 600})

    def as_user(self, cookie):
        self.client.cookies.clear()
        self.client.cookies.set("evui", cookie, path="/ui")

    def test_admin_flow_user_token_project_grant_and_secret_value_never_in_html(self):
        self.assertEqual(self.post("/ui/users", {"email": f"a{self.sfx}@ui.test", "display_name": "A <b>"}).status_code, 303)
        user = next(u for u in self.store.list_users(True) if u["email"] == f"a{self.sfx}@ui.test")
        shown = self.post("/ui/users/token", {"subject": user["subject"]})
        token = re.search(r"evk_[A-Za-z0-9_-]+", shown.text).group(0)
        self.assertEqual(self.store.resolve_token(token)["subject"], user["subject"])
        self.assertNotIn("<b>", shown.text)  # output is escaped
        users_html = self.client.get("/ui/users").text
        self.assertNotIn(token, users_html)  # the full token is never shown again...
        self.assertIn(f"evk_&hellip;{token[-8:]}", users_html)  # ...only its last 8 characters

        self.assertEqual(self.post("/ui/projects", {"slug": self.slug, "name": "UI project"}).status_code, 303)
        self.post("/ui/project/member", {"slug": self.slug, "subject": user["subject"], "role": "editor"})
        self.post("/ui/vault/save", {"name": f"DB{self.sfx}", "category": "credentials", "value": "hunter2-value", "project": self.slug})
        self.post("/ui/project/grants", {"slug": self.slug, "subject": user["subject"], "cat": "credentials"})
        self.assertEqual(self.store.vault_get(f"DB{self.sfx}", user["subject"]), "hunter2-value")

        self.client.cookies.set("evui", self.admin_cookie, path="/ui")
        html = self.client.get(f"/ui/project?slug={self.slug}").text
        self.assertIn(f"DB{self.sfx}", html)
        self.assertNotIn("hunter2-value", html)  # values are never in page HTML
        self.assertIn("checked", html)
        self.post("/ui/project/grants", {"slug": self.slug, "subject": user["subject"]})  # clear all categories
        from method.service.store import AccessDenied
        with self.assertRaises(AccessDenied):
            self.store.vault_get(f"DB{self.sfx}", user["subject"])
        self.post("/ui/project/vault/unshare", {"slug": self.slug, "name": f"DB{self.sfx}"})
        self.assertEqual(self.store.vault_list(self.admin, True, self.slug, include_unreadable=True), [])
        self.post("/ui/project/vault/delete", {"slug": self.slug, "name": f"DB{self.sfx}"})

    def test_member_sees_granted_secrets_only_and_can_fetch_value_for_copy(self):
        self.post("/ui/projects", {"slug": self.slug, "name": "Shared"})
        user = self.store.create_user(f"m{self.sfx}@ui.test", "M", True)
        self.post("/ui/project/member", {"slug": self.slug, "subject": user["subject"], "role": "editor"})
        k, d = f"KEY{self.sfx}", f"PWD{self.sfx}"
        self.post("/ui/vault/save", {"name": k, "category": "api-keys", "value": "k-secret-1", "project": self.slug})
        self.post("/ui/vault/save", {"name": d, "category": "credentials", "value": "p-secret-2", "project": self.slug})
        self.post("/ui/project/grants", {"slug": self.slug, "subject": user["subject"], "cat": "api-keys"})

        self.as_user(self.member_cookie(user["subject"], f"m{self.sfx}@ui.test"))
        page = self.client.get("/ui/vault")
        self.assertEqual(page.status_code, 200)
        self.assertIn(k, page.text)
        self.assertNotIn(d, page.text)  # category not granted
        self.assertNotIn("k-secret-1", page.text)  # values never in the page HTML
        self.assertIn("Copy", page.text)
        self.assertIn("nonce-", page.headers["content-security-policy"])
        self.assertNotIn("/ui/users", page.text)  # no admin navigation
        self.assertIn("Evidence secret", page.text)
        self.assertNotIn("My secrets", page.text)

        ok = self.client.post("/ui/vault/value", data={"csrf": "mcsrf", "name": k})
        self.assertEqual(ok.json(), {"value": "k-secret-1"})
        self.assertEqual(ok.headers["cache-control"], "no-store")
        denied = self.client.post("/ui/vault/value", data={"csrf": "mcsrf", "name": d})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("p-secret-2", denied.text)
        self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": "wrong", "name": k}).status_code, 403)
        self.assertEqual(self.client.post("/ui/users", data={"csrf": "mcsrf", "email": "x@y.test"}).headers["location"],
                         "/ui/vault")  # members cannot reach admin actions
        with self.store.connect() as conn:
            conn.execute("DELETE FROM vault_secrets WHERE name = ANY(%s)", ([k, d],))
            conn.execute("DELETE FROM projects WHERE slug = %s", (self.slug,))
            conn.execute("DELETE FROM audit_events WHERE actor_subject = %s", (user["subject"],))
            conn.execute("DELETE FROM users WHERE subject = %s", (user["subject"],))

    def test_users_create_and_share_their_own_secrets_with_other_users(self):
        a = self.store.create_user(f"alice{self.sfx}@ui.test", "Alice", True)
        b = self.store.create_user(f"bob{self.sfx}@ui.test", "Bob", True)
        name = f"CF{self.sfx}"
        try:
            self.as_user(self.member_cookie(a["subject"], a["email"], "ac"))
            made = self.client.post("/ui/vault/save", data={"csrf": "ac", "name": name, "category": "api-keys", "value": "cf-token-1"})
            self.assertEqual(made.headers["location"], "/ui/vault?msg=created")
            self.assertIn("Sharing", self.client.get(f"/ui/secret?name={name}").text)
            self.as_user(self.member_cookie(b["subject"], b["email"], "bc"))
            self.assertNotIn(name, self.client.get("/ui/vault").text)  # not shared yet
            self.assertEqual(self.client.get(f"/ui/secret?name={name}").status_code, 403)  # and not b's to manage
            self.assertEqual(self.client.post("/ui/secret/delete", data={"csrf": "bc", "name": name}).status_code, 403)

            self.as_user(self.member_cookie(a["subject"], a["email"], "ac"))
            self.client.post("/ui/secret/share", data={"csrf": "ac", "name": name, "user": b["subject"]})
            self.as_user(self.member_cookie(b["subject"], b["email"], "bc"))
            self.assertIn(name, self.client.get("/ui/vault").text)
            self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": "bc", "name": name}).json(), {"value": "cf-token-1"})
            self.assertEqual(self.client.get(f"/ui/secret?name={name}").status_code, 403)  # shared, but only the owner manages

            self.as_user(self.member_cookie(a["subject"], a["email"], "ac"))
            self.client.post("/ui/secret/share", data={"csrf": "ac", "name": name})  # unshare everyone
            self.as_user(self.member_cookie(b["subject"], b["email"], "bc"))
            self.assertEqual(self.client.post("/ui/vault/value", data={"csrf": "bc", "name": name}).status_code, 403)
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM vault_secrets WHERE name = %s", (name,))
                conn.execute("DELETE FROM audit_events WHERE project_id IS NULL AND actor_subject = ANY(%s)", ([a["subject"], b["subject"]],))
                conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([a["subject"], b["subject"]],))

    def test_token_page_shows_last_8_characters_and_a_short_list(self):
        u = self.store.create_user(f"hint{self.sfx}@ui.test", "Hint", True)
        try:
            self.as_user(self.member_cookie(u["subject"], u["email"], "hc"))
            tokens = []
            for i in range(6):
                made = self.client.post("/ui/token/new", data={"csrf": "hc", "label": f"key{i}"})
                tokens.append(re.search(r"evk_[A-Za-z0-9_-]+", made.text).group(0))
            for t in self.store.list_own_tokens(u["subject"]):
                if t["label"] != "key5":  # leave the newest one active, revoke key0..key4
                    self.client.post("/ui/token/revoke", data={"csrf": "hc", "id": t["id"]})
            html = self.client.get("/ui/token").text
            self.assertIn("Ends with", html)
            self.assertEqual(html.count("badge off"), 3)  # only the 3 newest revoked are listed
            self.assertIn("2 older revoked secrets not shown", html)
            self.assertIn(f"evk_&hellip;{tokens[5][-8:]}", html)  # the one still active
            self.assertNotIn(tokens[5], html)  # but never the whole secret
            self.assertNotIn(tokens[5][-20:], html)  # not even a longer tail
            self.as_user(self.admin_cookie)
            self.assertIn(f"evk_&hellip;{tokens[5][-8:]}", self.client.get("/ui/users").text)  # admins see the hint too
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM audit_events WHERE project_id IS NULL AND actor_subject = %s", (u["subject"],))
                conn.execute("DELETE FROM users WHERE subject = %s", (u["subject"],))

    def test_each_user_generates_and_revokes_their_own_evidence_secret(self):
        u = self.store.create_user(f"tok{self.sfx}@ui.test", "Tok", True)
        try:
            self.as_user(self.member_cookie(u["subject"], u["email"], "tc"))
            page = self.client.get("/ui/token")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Generate Evidence secret", page.text)
            self.assertNotIn("evk_", page.text)
            made = self.client.post("/ui/token/new", data={"csrf": "tc", "label": "my laptop"})
            token = re.search(r"evk_[A-Za-z0-9_-]+", made.text).group(0)
            self.assertEqual(self.store.resolve_token(token)["subject"], u["subject"])
            self.assertEqual(made.headers["cache-control"], "no-store")
            again = self.client.get("/ui/token").text
            self.assertNotIn(token, again)  # shown once only
            self.assertIn("my laptop", again)
            tid = self.store.list_own_tokens(u["subject"])[0]["id"]
            self.assertEqual(self.client.post("/ui/token/new", data={"csrf": "wrong"}).status_code, 403)
            self.client.post("/ui/token/revoke", data={"csrf": "tc", "id": tid})
            self.assertIsNone(self.store.resolve_token(token))
        finally:
            with self.store.connect() as conn:
                conn.execute("DELETE FROM audit_events WHERE project_id IS NULL AND actor_subject = %s", (u["subject"],))
                conn.execute("DELETE FROM users WHERE subject = %s", (u["subject"],))


class GoogleLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self):
        from types import SimpleNamespace
        return SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=self.key.public_key()))

    def token(self, **over):
        import time
        import jwt
        claims = {"iss": "https://accounts.google.com", "aud": "cid", "sub": "123", "email": "a@gmail.com",
                  "email_verified": True, "nonce": "n1", "iat": int(time.time()), "exp": int(time.time()) + 600}
        claims.update(over)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k"})

    def test_accepts_valid_and_rejects_bad_tokens(self):
        from method.service.ui import verify_google_id_token as verify
        self.assertEqual(verify(self.token(), self.jwks(), "cid", "n1")["email"], "a@gmail.com")
        for label, kwargs, nonce in (
            ("audience", {"aud": "other"}, "n1"), ("issuer", {"iss": "https://evil.example"}, "n1"),
            ("unverified", {"email_verified": False}, "n1"), ("nonce", {}, "wrong"),
            ("expired", {"exp": 1}, "n1"), ("no email", {"email": None}, "n1"),
        ):
            with self.subTest(label), self.assertRaises(Exception):
                verify(self.token(**kwargs), self.jwks(), "cid", nonce)


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class LoginUserTests(unittest.TestCase):
    def test_only_known_enabled_emails_or_admin_bootstrap_may_log_in(self):
        store = Store(CONNINFO)
        store.initialize()
        sfx = uuid.uuid4().hex[:8]
        email = f"Known{sfx}@Gmail.test"
        user = store.create_user(email, "K", True)
        try:
            self.assertEqual(store.login_user(email.lower(), "", False), user["subject"])  # case-insensitive
            self.assertIsNone(store.login_user(f"stranger{sfx}@gmail.test", "", False))  # not invited
            with self.assertRaises(ValueError):
                store.create_user(email.upper(), "dup", True)
            store.update_user(user["subject"], True, disabled=True)
            self.assertIsNone(store.login_user(email, "", False))  # disabled
            boot = store.login_user(f"admin{sfx}@gmail.test", "Boss", True)  # ADMIN_EMAILS bootstrap
            self.assertTrue(boot.startswith("local:"))
            self.assertEqual(store.login_user(f"admin{sfx}@gmail.test", "", False), boot)
        finally:
            with store.connect() as conn:
                conn.execute("DELETE FROM users WHERE lower(email) LIKE %s", (f"%{sfx}@gmail.test",))


if __name__ == "__main__":
    unittest.main()
