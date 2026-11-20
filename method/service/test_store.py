from __future__ import annotations

import os
import unittest
import uuid

from method.service.store import AccessDenied, RevisionConflict, Store

CONNINFO = os.environ.get("EVIDENCE_TEST_CONNINFO")


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class StoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(CONNINFO)
        self.store.initialize()
        suffix = uuid.uuid4().hex[:10]
        self.slugs = [f"pilot-{suffix}-{index}" for index in range(5)]
        self.subjects = [f"owner-{suffix}-{index}" for index in range(5)]
        self.reader = f"reader-{suffix}"
        self.editor = f"editor-{suffix}"
        self.projects = []
        for index, (slug, owner) in enumerate(zip(self.slugs, self.subjects)):
            content = f"# Project {index}\n\nInitial body {index}.\n"
            self.projects.append(self.store.create_project(slug, f"Project {index}", content, owner))
        self.store.add_member(self.slugs[0], self.reader, "reader", self.subjects[0])
        self.store.add_member(self.slugs[0], self.editor, "editor", self.subjects[0])

    def tearDown(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM projects WHERE slug = ANY(%s)", (self.slugs,))
            conn.execute("DELETE FROM users WHERE subject = ANY(%s)", (self.subjects + [self.reader, self.editor],))

    def test_project_isolation_roles_revision_conflict_and_audit(self):
        self.assertEqual(len(self.store.list_projects(self.reader)), 1)
        protocol = self.store.get_protocol(self.slugs[0], self.reader)
        self.assertEqual(protocol["revision"], 1)
        with self.assertRaises(AccessDenied):
            self.store.get_protocol(self.slugs[1], self.reader)
        with self.assertRaises(AccessDenied):
            self.store.update_protocol(self.slugs[0], "reader overwrite", 1, self.reader, "denied")

        updated = self.store.update_protocol(
            self.slugs[0], "editor update", 1, self.editor, "pilot edit"
        )
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(RevisionConflict) as conflict:
            self.store.update_protocol(self.slugs[0], "stale overwrite", 1, self.editor, "stale edit")
        self.assertEqual(conflict.exception.current_revision, 2)
        current = self.store.get_protocol(self.slugs[0], self.reader)
        self.assertEqual(current["content"], "editor update")
        self.assertEqual(current["revision"], 2)
        self.assertEqual(len(self.store.list_revisions(self.slugs[0], self.reader)), 2)
        self.assertEqual(
            {member["role"] for member in self.store.list_members(self.slugs[0], self.reader)},
            {"owner", "reader", "editor"},
        )
        self.assertEqual(len(self.store.list_audit(self.slugs[0], self.reader)), 4)
        self.store.record_approval(self.slugs[0], 2, 2, True, "pilot gate", self.subjects[0])
        self.assertEqual(self.store.list_audit(self.slugs[0], self.reader)[0]["event_type"], "phase.approval")

        with self.store.connect() as conn:
            counts = conn.execute(
                "SELECT count(*) AS count FROM audit_events WHERE project_id = %s",
                (self.projects[0]["id"],),
            ).fetchone()
        self.assertEqual(counts["count"], 5)

    def test_cannot_remove_last_owner(self):
        with self.assertRaisesRegex(ValueError, "last project owner"):
            self.store.remove_member(self.slugs[0], self.subjects[0], self.subjects[0])


if __name__ == "__main__":
    unittest.main()
