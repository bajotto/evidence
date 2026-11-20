"""Behavior tests for the central-mode hook: live header from the service, cache, offline fallback, quiet PostToolUse,
sync tracking and key safety. Uses a throwaway local HTTP server, never a real service or key."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOOK = ROOT / "method" / "protocol-header.sh"
TOKEN = "evk_" + "t" * 43
SLUG = "central-test"


def header_text(revision: int) -> str:
    return (f"<!-- PROTOCOL-HEADER:START -->\n# PROTOCOL HEADER — READ FIRST\n**Project:** central-test\n"
            f"**Current phase:** 2\nREVISION-MARKER-{revision}\n<!-- PROTOCOL-HEADER:END -->\n")


class FakeService:
    """Serves /api/protocol/header with a switchable behavior and records what it was sent."""

    def __init__(self):
        self.revision, self.mode, self.hits, self.auth, self.agents, self.redirect_to = 3, "ok", 0, [], [], ""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.hits += 1
                outer.auth.append(self.headers.get("Authorization", ""))
                outer.agents.append(self.headers.get("User-Agent", ""))
                if outer.mode == "403":
                    self.send_response(403); self.end_headers(); return
                if outer.mode == "redirect":
                    self.send_response(302); self.send_header("Location", outer.redirect_to); self.end_headers(); return
                body = json.dumps({"project_slug": SLUG, "name": "Central test", "revision": outer.revision,
                                   "updated_at": "2026-11-20T00:00:00", "header": header_text(outer.revision)}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown(); self.server.server_close()


class CentralHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = FakeService()
        self.addCleanup(lambda: self.service.server.socket.fileno() != -1 and self.service.stop())
        self.project = self.tmp / "project"
        (self.project / ".evidence").mkdir(parents=True)
        self.manifest({"service_url": self.service.url, "project_slug": SLUG, "protocol_source": "central"})
        (self.project / "EVIDENCE_PROTOCOL.md").write_text("STALE_LOCAL_PROTOCOL_MARKER\n", encoding="utf-8")

    def manifest(self, data):
        (self.project / ".evidence" / "project.json").write_text(json.dumps(data), encoding="utf-8")

    def run_hook(self, event="UserPromptSubmit", session="s1", token=TOKEN, ttl="60", cwd=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp / "home"), "XDG_CACHE_HOME": str(self.tmp / "cache"),
               "EVIDENCE_HOOK_CACHE_TTL": ttl, "EVIDENCE_HOOK_TIMEOUT": "2"}
        if token:
            env["EVIDENCE_TOKEN"] = token
        data = {"cwd": str(cwd or self.project), "hook_event_name": event, "session_id": session}
        out = subprocess.run(["bash", str(HOOK), "hook"], input=json.dumps(data), env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)  # the key is never echoed
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_session_start_injects_the_live_header_with_the_key_and_a_named_client(self):
        ctx = self.run_hook("SessionStart")
        self.assertIn("CENTRAL EVIDENCE MODE", ctx)
        self.assertIn(SLUG, ctx)
        self.assertIn("LIVE PROTOCOL HEADER (revision 3, live from the service)", ctx)
        self.assertIn("REVISION-MARKER-3", ctx)
        self.assertNotIn("STALE_LOCAL_PROTOCOL_MARKER", ctx)  # the central copy wins over a leftover local file
        self.assertEqual((self.service.hits, self.service.auth, self.service.agents),
                         (1, [f"Bearer {TOKEN}"], ["evidence-hook/1.0"]))
        cache = next((self.tmp / "cache" / "evidence").glob("*.json"))
        self.assertNotIn(TOKEN, cache.read_text())  # never cached
        self.assertEqual(oct(cache.stat().st_mode & 0o777), "0o600")

    def test_prompts_use_the_cache_so_there_is_no_network_call_on_every_prompt(self):
        self.run_hook("SessionStart")
        ctx = self.run_hook("UserPromptSubmit")
        self.assertIn("REVISION-MARKER-3", ctx)  # still injected on every prompt, like the old protocol
        self.assertIn("from the last fetch", ctx)
        self.assertEqual(self.service.hits, 1)

    def test_after_tool_calls_the_hook_is_quiet_until_the_revision_changes(self):
        self.run_hook("SessionStart", ttl="0")
        self.assertEqual(self.run_hook("PostToolUse", ttl="0"), "")  # the old hook repeated the header after every tool call
        self.assertEqual(self.run_hook("PostToolUse", ttl="0"), "")
        self.service.revision = 4
        updated = self.run_hook("PostToolUse", ttl="0")
        self.assertIn("PROTOCOL UPDATED to revision 4", updated)
        self.assertIn("REVISION-MARKER-4", updated)
        self.assertEqual(self.run_hook("PostToolUse", ttl="0"), "")  # and quiet again
        self.assertIn("REVISION-MARKER-4", self.run_hook("PostToolUse", session="another-session", ttl="0"))  # new sessions still get it once

    def test_offline_falls_back_to_the_last_header_marked_stale(self):
        self.run_hook("SessionStart")
        self.service.stop()
        ctx = self.run_hook("UserPromptSubmit", ttl="0")
        self.assertIn("REVISION-MARKER-3", ctx)
        self.assertIn("STALE", ctx)
        self.assertNotIn("nothing is cached", ctx)

    def test_offline_with_nothing_cached_says_so_instead_of_guessing(self):
        self.service.stop()
        ctx = self.run_hook("UserPromptSubmit")
        self.assertIn("CENTRAL EVIDENCE MODE", ctx)
        self.assertIn("could not be reached and nothing is cached", ctx)
        self.assertNotIn("REVISION-MARKER", ctx)

    def test_missing_key_explains_what_to_do_and_makes_no_request(self):
        ctx = self.run_hook(token="")
        self.assertIn("EVIDENCE_TOKEN is not set", ctx)
        self.assertEqual(self.service.hits, 0)

    def test_a_rejected_key_is_reported_not_hidden(self):
        self.service.mode = "403"
        self.assertIn("rejected the key", self.run_hook())

    def test_redirects_are_never_followed_so_the_key_cannot_leave_the_named_host(self):
        other = FakeService()
        self.addCleanup(lambda: other.server.socket.fileno() != -1 and other.stop())
        self.service.mode, self.service.redirect_to = "redirect", other.url.replace("/mcp", "/api/protocol/header?project=x")
        ctx = self.run_hook()
        self.assertEqual(other.hits, 0)
        self.assertEqual(other.auth, [])
        self.assertNotIn("REVISION-MARKER", ctx)

    def test_an_untrusted_manifest_is_refused_before_any_request(self):
        self.manifest({"service_url": "http://evil.example/mcp", "project_slug": SLUG, "protocol_source": "central"})
        self.assertIn("CONFIGURATION FAIL", self.run_hook())
        self.assertEqual(self.service.hits, 0)

    def test_projects_without_a_manifest_keep_the_original_local_behavior(self):
        legacy = self.tmp / "legacy"
        legacy.mkdir()
        shutil.copy(ROOT / "method" / "PROJECT_PROTOCOL_TEMPLATE.md", legacy / "EVIDENCE_PROTOCOL.md")
        ctx = self.run_hook(cwd=legacy)
        self.assertIn("PROTOCOL HEADER", ctx)
        self.assertNotIn("CENTRAL EVIDENCE MODE", ctx)
        self.assertEqual(self.service.hits, 0)

    @unittest.skipUnless(shutil.which("jq"), "jq is needed by the session-start wrapper")
    def test_the_global_session_start_hook_carries_the_live_header_too(self):
        home = self.tmp / "home-claude"
        (home / ".claude" / "hooks").mkdir(parents=True)
        shutil.copy(HOOK, home / ".claude" / "hooks" / "protocol-header.sh")
        env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_DIR": str(home / ".claude"), "EVIDENCE_TOKEN": TOKEN,
               "XDG_CACHE_HOME": str(self.tmp / "cache2")}
        out = subprocess.run(["bash", str(ROOT / "claude" / "hooks" / "session-start-protocol-global.sh")],
                             input=json.dumps({"cwd": str(self.project), "session_id": "s9"}), env=env, capture_output=True, text=True, timeout=30)
        ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("LIVE PROTOCOL HEADER (revision 3, live from the service)", ctx)
        self.assertIn("REVISION-MARKER-3", ctx)
        self.assertNotIn(TOKEN, out.stdout)


if __name__ == "__main__":
    unittest.main()
