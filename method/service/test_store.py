from __future__ import annotations

import os
import unittest
import uuid

from method.service.store import AccessDenied, PhaseGateBlocked, RevisionConflict, Store, declared_phase

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

    def _doc(self, phase: int) -> str:
        return f"# Gate project\n\n**Status:** Phase {phase} in progress\n\n### Phase {phase}\nbody\n"

    def _gated(self, phase: int = 1):
        """Project 1 with the gate on at `phase`; returns (slug, owner, current revision)."""
        slug, owner = self.slugs[1], self.subjects[1]
        rev = self.store.update_protocol(slug, self._doc(phase), 1, owner, "declare phase")["revision"]
        self.store.set_phase_gate(slug, True, owner)
        return slug, owner, rev

    def test_gate_is_off_by_default(self):
        slug, owner = self.slugs[1], self.subjects[1]
        rev = self.store.update_protocol(slug, self._doc(1), 1, owner, "p1")["revision"]
        self.store.update_protocol(slug, self._doc(4), rev, owner, "jump freely")

    def test_advance_needs_current_owner_approval(self):
        slug, owner, rev = self._gated(1)
        with self.assertRaisesRegex(PhaseGateBlocked, "no current approval"):
            self.store.update_protocol(slug, self._doc(2), rev, owner, "advance")
        self.store.record_approval(slug, 1, rev, True, "pilot ok", owner)
        rev = self.store.update_protocol(slug, self._doc(2), rev, owner, "advance")["revision"]
        events = [e["event_type"] for e in self.store.list_audit(slug, owner)]
        self.assertIn("phase.advanced", events)
        with self.assertRaises(PhaseGateBlocked):  # phase 2 itself is not approved yet
            self.store.update_protocol(slug, self._doc(3), rev, owner, "advance again")

    def test_later_rejection_revokes_approval(self):
        slug, owner, rev = self._gated(1)
        self.store.record_approval(slug, 1, rev, True, "ok", owner)
        self.store.record_approval(slug, 1, rev, False, "withdrawn", owner)
        with self.assertRaises(PhaseGateBlocked):
            self.store.update_protocol(slug, self._doc(2), rev, owner, "advance")

    def test_approval_from_before_entering_the_phase_does_not_count(self):
        slug, owner, rev = self._gated(2)
        self.store.record_approval(slug, 2, rev, True, "ok", owner)
        rev = self.store.update_protocol(slug, self._doc(3), rev, owner, "advance")["revision"]
        rev = self.store.update_protocol(slug, self._doc(2), rev, owner, "regress")["revision"]  # re-enters phase 2
        self.assertIn("phase.regressed", [e["event_type"] for e in self.store.list_audit(slug, owner)])
        with self.assertRaises(PhaseGateBlocked):  # the old approval predates re-entering phase 2
            self.store.update_protocol(slug, self._doc(3), rev, owner, "advance")

    def test_jump_and_missing_phase_are_refused(self):
        slug, owner, rev = self._gated(1)
        self.store.record_approval(slug, 1, rev, True, "ok", owner)
        with self.assertRaisesRegex(PhaseGateBlocked, "cannot jump"):
            self.store.update_protocol(slug, self._doc(3), rev, owner, "jump")
        with self.assertRaisesRegex(PhaseGateBlocked, "must declare"):
            self.store.update_protocol(slug, "# no phase here\n", rev, owner, "drop phase")

    def test_only_owner_approves_and_toggles_when_gated(self):
        slug = self.slugs[0]
        owner = self.subjects[0]
        rev = self.store.update_protocol(slug, self._doc(1), 1, owner, "p1")["revision"]
        with self.assertRaises(AccessDenied):
            self.store.set_phase_gate(slug, True, self.editor)
        self.store.set_phase_gate(slug, True, owner)
        with self.assertRaises(AccessDenied):
            self.store.record_approval(slug, 1, rev, True, "self-approve", self.editor)
        self.store.record_approval(slug, 1, rev, True, "ok", owner)
        self.store.set_phase_gate(slug, False, owner)
        self.store.record_approval(slug, 1, rev, True, "editor ok when gate off", self.editor)

    def test_enabling_requires_a_declared_phase(self):
        with self.assertRaisesRegex(PhaseGateBlocked, "does not declare"):
            self.store.set_phase_gate(self.slugs[1], True, self.subjects[1])

    def test_concurrent_advances_cannot_both_pass_the_gate(self):
        import threading
        slug, owner, rev = self._gated(1)
        self.store.record_approval(slug, 1, rev, True, "ok", owner)
        results = []

        def advance(target):
            try:
                results.append(self.store.update_protocol(slug, self._doc(target), rev, owner, f"to {target}")["revision"])
            except (RevisionConflict, PhaseGateBlocked) as exc:
                results.append(exc)

        threads = [threading.Thread(target=advance, args=(n,)) for n in (2, 2, 3)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(isinstance(r, int) for r in results), 1)
        self.assertEqual(declared_phase(self.store.get_protocol(slug, owner)["content"]), 2)  # the jump to 3 never landed


class DeclaredPhaseTests(unittest.TestCase):
    def test_matches_the_header_script_rules(self):
        self.assertEqual(declared_phase("**Status:** Phase 2 (Pilot) now\n\n### Phase 1\n### Phase 3"), 2)
        self.assertEqual(declared_phase("### Phase 1\n### Phase 2"), 2)
        self.assertEqual(declared_phase("**Estado:** Fase 3\n"), 3)
        self.assertIsNone(declared_phase("nothing"))
        wrapped = "<!-- PROTOCOL-HEADER:START -->\n**Status:** Phase 9\n<!-- PROTOCOL-HEADER:END -->\n### Phase 1"
        self.assertEqual(declared_phase(wrapped), 1)  # the generated header block is never the source


if __name__ == "__main__":
    unittest.main()
