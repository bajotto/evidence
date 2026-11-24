"""The pushable tree and the git hooks must keep instance-specific details out of this public repo."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import public_safe

ROOT = Path(__file__).resolve().parent


class PublicSafeTests(unittest.TestCase):
    def test_working_tree_is_clean(self):
        self.assertEqual(public_safe.worktree(), [], "instance-specific details in files that would be pushed")

    def test_env_files_are_ignored(self):
        for name in (".env", "method/service/.env", ".env.production"):
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode, 0, name)

    def test_scanner_flags_each_category_without_echoing_the_match(self):
        samples = {
            "private IP": "host 192.168.7.9", "ssh": "run ssh deploy@box", "key": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "notes": "see access.md", "hostname": "on srv07", "env cred": "DB_PASSWORD=Sup3rS3cretValue",
            "token": "ghp_" + "a" * 36, "home": "see /home/alice/project/x",
        }
        for label, text in samples.items():
            hits = public_safe.scan("f", text)
            self.assertTrue(hits, label)
            self.assertNotIn(text, " ".join(hits))
        for ok in ("host 192.168.50.10", "PGPASSWORD=", "KEY_PASSWORD=<set-me>", "TOKEN=${EVIDENCE_TOKEN}", "/home/user/x",
                   "<!-- PROTOCOL-HEADER:START -->\n/home/alice/.claude\n<!-- PROTOCOL-HEADER:END -->"):
            self.assertEqual(public_safe.scan("f", ok), [], ok)

    def test_hooks_block_staged_content_message_and_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t"}

            def run(*cmd, check=True, **kw):
                return subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, check=check, **kw)

            run("git", "init", "-q")
            hooks = repo / ".githooks"
            hooks.mkdir()
            for name in ("pre-commit", "commit-msg", "pre-push"):
                (hooks / name).write_text((ROOT / ".githooks" / name).read_text())
                (hooks / name).chmod(0o755)
            (repo / "public_safe.py").write_text((ROOT / "public_safe.py").read_text())
            run("git", "config", "core.hooksPath", ".githooks")
            run("git", "add", "public_safe.py", ".githooks")
            run("git", "commit", "-q", "-m", "init")

            (repo / "a.txt").write_text("deploy to 10.1.2.3\n")
            run("git", "add", "a.txt")
            blocked = run("git", "commit", "-m", "ok message", check=False)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("private IP", blocked.stderr)
            self.assertNotIn("10.1.2.3", blocked.stderr + blocked.stdout)

            (repo / "a.txt").write_text("fine\n")
            run("git", "add", "a.txt")
            msg = run("git", "commit", "-m", "uses srv09 box", check=False)
            self.assertNotEqual(msg.returncode, 0)
            self.assertIn("internal hostname", msg.stderr)
            self.assertEqual(run("git", "commit", "-q", "-m", "clean change", check=False).returncode, 0)

            # a bad commit made with --no-verify is still stopped by pre-push
            (repo / "b.txt").write_text("ssh root@somewhere\n")
            run("git", "add", "b.txt")
            run("git", "commit", "-q", "--no-verify", "-m", "sneaky")
            bare = Path(tmp) / "remote.git"
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
            run("git", "remote", "add", "origin", str(bare))
            pushed = run("git", "push", "origin", "HEAD:refs/heads/main", check=False)
            self.assertNotEqual(pushed.returncode, 0)
            self.assertIn("ssh user@host", pushed.stderr)


if __name__ == "__main__":
    unittest.main()
