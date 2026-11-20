from __future__ import annotations

import base64
import os
import unittest
import uuid

from cryptography.exceptions import InvalidTag

from method.service import vault_crypto
from method.service.store import AccessDenied, ProjectNotFound, Store, normalize_join_key, slug_from_join_key

KEY = base64.b64encode(os.urandom(32)).decode()
CONNINFO = os.environ.get("EVIDENCE_TEST_CONNINFO")


class CryptoTests(unittest.TestCase):
    def setUp(self):
        os.environ["VAULT_MASTER_KEY"] = KEY

    def test_round_trip_and_tamper_rejection(self):
        nonce, blob = vault_crypto.encrypt("s3cret-value", "p:NAME")
        self.assertNotIn(b"s3cret", blob)
        self.assertEqual(vault_crypto.decrypt(nonce, blob, "p:NAME"), "s3cret-value")
        with self.assertRaises(InvalidTag):
            vault_crypto.decrypt(nonce, blob, "p:OTHER")  # AAD binds ciphertext to project+name

    def test_bad_key_fails_fast(self):
        os.environ["VAULT_MASTER_KEY"] = "short"
        with self.assertRaises(RuntimeError):
            vault_crypto.encrypt("x", "a")


class JoinKeyTests(unittest.TestCase):
    def test_ssh_https_and_credentials_normalize_to_one_key(self):
        keys = {normalize_join_key(v) for v in (
            "git@github.com:Acme/Repo.git", "https://github.com/acme/repo", "https://tok:x@github.com/acme/repo.git/")}
        self.assertEqual(keys, {"github.com/acme/repo"})
        self.assertEqual(slug_from_join_key("github.com/acme/repo"), "acme-repo")
        with self.assertRaises(ValueError):
            normalize_join_key("a b")


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class JoinAndTokenTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(CONNINFO)
        self.store.initialize()
        self.sfx = uuid.uuid4().hex[:10]
        self.key = f"git.example/org/repo-{self.sfx}"
        self.users = [self.store.create_user(f"u{i}-{self.sfx}@x.test", f"U{i}", True) for i in range(2)]

    def tearDown(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM projects WHERE join_key = %s", (self.key,))
            conn.execute("DELETE FROM users WHERE subject = ANY(%s)", ([u["subject"] for u in self.users],))

    def test_last_used_is_refreshed_at_most_every_few_minutes(self):
        tok = self.store.issue_token(self.users[0]["subject"], "throttle", True)
        with self.store.connect() as conn:
            conn.execute("UPDATE user_tokens SET last_used = now() - interval '1 hour' WHERE id = %s", (tok["id"],))
        self.store.resolve_token(tok["token"])  # stale: refreshed
        with self.store.connect() as conn:
            first = conn.execute("SELECT last_used FROM user_tokens WHERE id = %s", (tok["id"],)).fetchone()["last_used"]
        self.store.resolve_token(tok["token"])  # fresh: no write
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT last_used FROM user_tokens WHERE id = %s", (tok["id"],)).fetchone()["last_used"], first)
            self.assertGreater(first, conn.execute("SELECT now() - interval '1 minute' AS t").fetchone()["t"])

    def test_token_lifecycle_and_admin_gate(self):
        with self.assertRaises(AccessDenied):
            self.store.create_user("a@x.test", "", False)
        tok = self.store.issue_token(self.users[0]["subject"], "laptop", True)
        self.assertEqual(self.store.resolve_token(tok["token"])["subject"], self.users[0]["subject"])
        self.assertIsNone(self.store.resolve_token("evk_wrong"))
        with self.store.connect() as conn:  # only the hash is stored
            stored = conn.execute("SELECT token_hash FROM user_tokens WHERE id = %s", (tok["id"],)).fetchone()
        self.assertNotIn(tok["token"], stored["token_hash"])
        self.store.update_user(self.users[0]["subject"], True, disabled=True)
        self.assertIsNone(self.store.resolve_token(tok["token"]))
        self.store.update_user(self.users[0]["subject"], True, disabled=False)
        self.store.revoke_token(tok["id"], True)
        self.assertIsNone(self.store.resolve_token(tok["token"]))

    def test_join_creates_then_adds_idempotently(self):
        a, b = (u["subject"] for u in self.users)
        first = self.store.join_project(a, self.key, "Repo", "# Repo\n")
        self.assertTrue(first["created"])
        self.assertEqual(first["role"], "owner")
        second = self.store.join_project(b, self.key, "Repo", "# Repo\n")
        self.assertEqual((second["created"], second["role"], second["project_slug"]),
                         (False, "editor", first["project_slug"]))
        again = self.store.join_project(a, self.key, "Repo", "# Repo\n")  # owner is not downgraded
        self.assertEqual(again["role"], "owner")
        self.assertEqual({m["role"] for m in self.store.list_members(first["project_slug"], a)}, {"owner", "editor"})
        self.assertEqual(self.store.vault_list(b, False, first["project_slug"]), [])  # joined, but nothing shared


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class VaultStoreTests(unittest.TestCase):
    def setUp(self):
        os.environ["VAULT_MASTER_KEY"] = KEY
        self.store = Store(CONNINFO)
        self.store.initialize()
        sfx = uuid.uuid4().hex[:10]
        self.sfx = sfx
        self.owner, self.powner, self.m1, self.m2, self.direct, self.stranger = (
            self.store.create_user(f"{n}-{sfx}@v.test", n, True)["subject"]
            for n in ("secretowner", "projectowner", "member1", "member2", "direct", "stranger"))
        self.slug_a, self.slug_b = f"va-{sfx}", f"vb-{sfx}"
        self.store.create_project(self.slug_a, "A", "# a\n", self.powner)
        self.store.create_project(self.slug_b, "B", "# b\n", self.owner)
        self.store.add_member(self.slug_a, self.owner, "editor", self.powner)  # may share into A
        self.store.add_member(self.slug_a, self.m1, "reader", self.powner)
        self.store.add_member(self.slug_a, self.m2, "reader", self.powner)
        self.store.add_member(self.slug_b, self.m1, "reader", self.owner)
        self.names = []

    def tearDown(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM vault_secrets WHERE name LIKE %s", (f"T{self.sfx}%",))
            conn.execute("DELETE FROM projects WHERE slug = ANY(%s)", ([self.slug_a, self.slug_b],))
            conn.execute("DELETE FROM audit_events WHERE project_id IS NULL AND actor_subject IN "
                         "(SELECT subject FROM users WHERE email LIKE %s)", (f"%-{self.sfx}@v.test",))
            conn.execute("DELETE FROM users WHERE email LIKE %s", (f"%-{self.sfx}@v.test",))

    def n(self, suffix):
        return f"T{self.sfx}_{suffix}"

    def test_sharing_rules_projects_users_and_categories(self):
        db, api = self.n("DB"), self.n("API")
        self.store.vault_put(db, "credentials", "pw-123", self.owner, project_slug=self.slug_a)
        self.store.vault_put(api, "api-keys", "sk-456", self.owner)  # private: shared with nobody yet
        self.store.set_member_categories(self.slug_a, self.m1, ["credentials"], self.powner)

        self.assertEqual(self.store.vault_get(db, self.owner), "pw-123")  # owner always
        self.assertEqual(self.store.vault_get(db, self.m1), "pw-123")  # member with the category
        self.assertEqual(self.store.vault_get(db, self.powner), "pw-123")  # project owner reads everything shared in
        for who in (self.m2, self.stranger):  # no category grant / not in the project
            with self.assertRaises(AccessDenied):
                self.store.vault_get(db, who)
        with self.assertRaises(AccessDenied):
            self.store.vault_get(api, self.powner)  # not shared with project A
        with self.assertRaises(AccessDenied):
            self.store.vault_get(db, self.stranger)

        # direct user share ignores categories and projects
        self.store.set_secret_shares(api, [], [self.direct], self.owner)
        self.assertEqual(self.store.vault_get(api, self.direct), "sk-456")
        self.assertEqual([x["name"] for x in self.store.vault_list(self.direct)], [api])
        self.assertEqual(self.store.vault_list(self.stranger), [])

        # one secret, many projects: shared into B as well, project-scoped reads see only that route
        self.store.set_secret_shares(db, [self.slug_a, self.slug_b], [], self.owner)
        self.assertEqual(self.store.vault_get(db, self.m1, self.slug_a), "pw-123")
        self.assertEqual(self.store.vault_get(db, self.m1, self.slug_b), "pw-123")  # in scope of B, readable via A
        with self.assertRaises(AccessDenied):
            self.store.vault_get(api, self.direct, self.slug_b)  # readable by direct share, but not part of project B
        scoped = self.store.vault_list(self.owner, False, self.slug_a)
        self.assertEqual([x["name"] for x in scoped], [db])
        listed = {x["name"]: x for x in self.store.vault_list(self.owner)}
        self.assertEqual(sorted(listed[db]["projects"]), sorted([self.slug_a, self.slug_b]))
        self.assertEqual((listed[api]["projects"], listed[api]["users"]), ([], 1))

    def test_ciphertext_at_rest_audit_and_admin_cannot_read(self):
        name = self.n("AT")
        self.store.vault_put(name, "env", "plain-value-9", self.owner)
        with self.store.connect() as conn:
            row = conn.execute("SELECT ciphertext FROM vault_secrets WHERE name = %s", (name,)).fetchone()
            self.assertNotIn(b"plain-value-9", bytes(row["ciphertext"]))
        with self.assertRaises(AccessDenied):
            self.store.vault_get(name, self.stranger)
        self.assertEqual(len(self.store.vault_list(self.stranger, True)), 0)  # admin flag alone shows nothing readable
        self.assertEqual(len([x for x in self.store.vault_list(self.stranger, True, include_unreadable=True) if x["name"] == name]), 1)
        self.store.vault_get(name, self.owner)
        with self.store.connect() as conn:
            reads = conn.execute("SELECT count(*) AS n FROM audit_events WHERE event_type = 'vault.read' AND actor_subject = %s",
                                 (self.owner,)).fetchone()["n"]
        self.assertGreaterEqual(reads, 1)

    def test_only_the_owner_rotates_shares_or_deletes(self):
        name = self.n("OWN")
        self.assertTrue(self.store.vault_put(name, "env", "v1", self.owner)["created"])
        self.assertEqual(self.store.vault_put(name, "env", "v2", self.owner)["revision"], 2)
        self.assertEqual(self.store.vault_get(name, self.owner), "v2")
        for call in (lambda: self.store.vault_put(name, "env", "hijack", self.m1),
                     lambda: self.store.set_secret_shares(name, [], [self.m1], self.m1),
                     lambda: self.store.vault_delete(name, self.m1)):
            with self.assertRaises(AccessDenied):
                call()
        self.store.vault_delete(name, self.owner)
        self.assertEqual(self.store.vault_list(self.owner), [])

    def test_sharing_is_limited_to_projects_you_own_or_edit_and_preserves_others(self):
        name = self.n("SH")
        self.store.vault_put(name, "env", "v", self.owner)
        with self.assertRaises(AccessDenied):  # m1 is only a reader of B, and not in A as editor
            self.store.vault_put(self.n("X"), "env", "v", self.m1, project_slug=self.slug_b)
        self.store.set_secret_shares(name, [self.slug_a, self.slug_b], [], self.owner)
        # the A project owner shares it nowhere else; project-owner edits must not touch B
        self.store.add_member(self.slug_a, self.powner, "owner", self.powner)
        self.store.set_secret_shares(name, [self.slug_a], [], self.owner, is_admin=False)
        shares = self.store.secret_shares(name, self.owner)
        self.assertEqual(shares["projects"], [self.slug_a])  # owner manages A and B and removed B explicitly
        with self.assertRaises(AccessDenied):
            self.store.set_secret_shares(name, [self.slug_b], [], self.powner)  # powner is not the secret's owner

    def test_update_details_without_touching_the_value_then_rotate(self):
        name = self.n("UPD")
        self.store.vault_put(name, "env", "keep-me", self.owner, description="first")
        out = self.store.vault_update(name, self.owner, category="infra", description="second")
        self.assertEqual((out["value_changed"], out["revision"]), (False, 1))
        self.assertEqual(self.store.vault_get(name, self.owner), "keep-me")
        listed = {x["name"]: x for x in self.store.vault_list(self.owner)}[name]
        self.assertEqual((listed["category"], listed["description"]), ("infra", "second"))
        self.assertEqual(self.store.vault_update(name, self.owner, value="new\nvalue")["revision"], 2)
        self.assertEqual(self.store.vault_get(name, self.owner), "new\nvalue")  # multi-line survives encryption
        with self.assertRaises(AccessDenied):
            self.store.vault_update(name, self.m1, description="not mine")
        with self.assertRaisesRegex(ValueError, "500"):
            self.store.vault_update(name, self.owner, description="x" * 501)

    def test_token_list_shows_all_active_and_only_the_three_newest_revoked_with_last_8_characters(self):
        issued = [self.store.issue_own_token(self.m1, f"t{i}") for i in range(6)]
        for t in issued[:5]:  # revoke the first five, oldest first
            self.store.revoke_own_token(t["id"], self.m1)
        listed = self.store.list_own_tokens(self.m1)
        active = [t for t in listed if not t["revoked_at"]]
        revoked = [t for t in listed if t["revoked_at"]]
        self.assertEqual([t["label"] for t in active], ["t5"])
        self.assertEqual([t["label"] for t in revoked], ["t4", "t3", "t2"])  # most recently revoked first
        self.assertEqual(self.store.count_own_revoked(self.m1), 5)
        by_label = {f"t{i}": t for i, t in enumerate(issued)}
        for t in listed:
            self.assertEqual(t["token_hint"], by_label[t["label"]]["token"][-8:])  # last 8 characters, never more
            self.assertEqual(len(t["token_hint"]), 8)
        extra = [self.store.issue_own_token(self.m1, f"a{i}") for i in range(3)]
        self.assertEqual(sum(1 for t in self.store.list_own_tokens(self.m1) if not t["revoked_at"]), 4)  # every active one stays
        admin_view = self.store.issue_token(self.m2, "by-admin", True)
        self.assertEqual(self.store.list_tokens(self.m2, True)[0]["token_hint"], admin_view["token"][-8:])
        self.assertIsNotNone(extra)

    def test_read_tracking_skips_writes_when_nothing_changed(self):
        slug = self.slug_a
        self.store.touch_read(slug, self.m1, 1, "hook")
        with self.store.connect() as conn:
            conn.execute("UPDATE protocol_reads SET read_at = now() - interval '1 hour' WHERE subject = %s", (self.m1,))
        self.store.touch_read(slug, self.m1, 1, "hook")  # same revision and channel but stale: refreshed
        def read_at():
            with self.store.connect() as conn:
                return conn.execute("SELECT read_at, revision, via FROM protocol_reads WHERE subject = %s", (self.m1,)).fetchone()
        stamped = read_at()
        self.store.touch_read(slug, self.m1, 1, "hook")  # unchanged and fresh: no write
        self.assertEqual(read_at(), stamped)
        self.store.touch_read(slug, self.m1, 2, "hook")  # a new revision is always recorded
        self.assertEqual(read_at()["revision"], 2)
        self.store.touch_read(slug, self.m1, 2, "mcp")  # and so is a new channel
        self.assertEqual(read_at()["via"], "mcp")

    def test_sync_status_tells_who_has_read_the_current_protocol_revision(self):
        slug = self.slug_a  # members: powner (owner), owner (editor), m1 and m2 (readers)
        self.assertEqual({m["status"] for m in self.store.sync_status(slug, self.powner)["members"]}, {"never"})
        self.store.touch_read(slug, self.m1, 1, "mcp")
        self.store.touch_read(slug, self.stranger, 1, "mcp")  # not a member: ignored
        st = self.store.sync_status(slug, self.powner)
        by = {m["email"].split("-")[0]: m for m in st["members"]}
        self.assertEqual((by["member1"]["status"], by["member1"]["via"], by["member1"]["read_revision"]), ("current", "mcp", 1))
        self.assertNotIn("stranger", by)
        self.assertEqual((st["synced"], st["total"], st["current_revision"]), (1, 4, 1))

        self.store.update_protocol(slug, "# changed\n", 1, self.powner, "new revision")  # now everyone is behind or never
        by = {m["email"].split("-")[0]: m for m in self.store.sync_status(slug, self.powner)["members"]}
        self.assertEqual((by["member1"]["status"], by["member1"]["behind"]), ("behind", 1))
        self.assertEqual(by["member2"]["status"], "never")
        self.store.touch_read(slug, self.m1, 2, "web")
        self.store.touch_read(slug, self.m2, 2, "mcp")
        st = self.store.sync_status(slug, self.m1)  # any member may look
        self.assertEqual({m["email"].split("-")[0]: m["status"] for m in st["members"]},
                         {"member1": "current", "member2": "current", "secretowner": "never", "projectowner": "never"})
        self.assertEqual(st["synced"], 2)
        with self.assertRaises(AccessDenied):
            self.store.sync_status(slug, self.stranger)

    def test_self_service_evidence_secret(self):
        issued = self.store.issue_own_token(self.m1, "laptop")
        self.assertEqual(self.store.resolve_token(issued["token"])["subject"], self.m1)
        self.assertEqual(len(self.store.list_own_tokens(self.m1)), 1)
        with self.assertRaises(ProjectNotFound):
            self.store.revoke_own_token(issued["id"], self.m2)  # cannot revoke someone else's
        self.store.revoke_own_token(issued["id"], self.m1)
        self.assertIsNone(self.store.resolve_token(issued["token"]))
        for _ in range(10):
            self.store.issue_own_token(self.m2, "x")
        with self.assertRaisesRegex(ValueError, "10 active"):
            self.store.issue_own_token(self.m2, "one too many")
        self.store.update_user(self.m1, True, disabled=True)
        with self.assertRaises(AccessDenied):
            self.store.issue_own_token(self.m1, "disabled users cannot")


if __name__ == "__main__":
    unittest.main()
