import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from evidence_install import apply_changes, project_config, server_config


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_does_not_write(self):
        outputs = project_config(self.target, "claude", "https://mcp.example/mcp", "sample-project", True)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_changes(outputs, dry_run=True, target_root=self.target)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_all_clients_install_idempotently_in_selected_target(self):
        for client in ("claude", "devin", "codex", "cursor", "trae"):
            with self.subTest(client=client), tempfile.TemporaryDirectory(prefix="evidence project with spaces ") as temp:
                target = Path(temp)
                if client == "codex":
                    (target / "AGENTS.md").write_text("Existing project rules.\n", encoding="utf-8")
                outputs = project_config(target, client, "https://mcp.example/mcp", "sample-project", True)
                with contextlib.redirect_stdout(io.StringIO()):
                    apply_changes(outputs, dry_run=False, target_root=target)
                first = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
                second_outputs = project_config(target, client, "https://mcp.example/mcp", "sample-project", True)
                with contextlib.redirect_stdout(io.StringIO()):
                    apply_changes(second_outputs, dry_run=False, target_root=target)
                second = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
                self.assertEqual(first, second)
                self.assertIn(Path(".evidence/project.json"), first)
                if client == "codex":
                    config = tomllib.loads((target / ".codex/config.toml").read_text(encoding="utf-8"))
                    self.assertEqual(config["mcp_servers"]["evidence"]["url"], "https://mcp.example/mcp")
                    self.assertTrue((target / "AGENTS.md").read_text(encoding="utf-8").startswith("Existing project rules."))
                else:
                    config_path = {
                        "claude": ".mcp.json",
                        "devin": ".devin/mcp_config.json",
                        "cursor": ".cursor/mcp.json",
                        "trae": ".trae/mcp.json",
                    }[client]
                    config = json.loads((target / config_path).read_text(encoding="utf-8"))
                    self.assertEqual(config["mcpServers"]["evidence"]["url"], "https://mcp.example/mcp")

    def test_merges_existing_json_and_preserves_other_servers(self):
        path = self.target / ".cursor/mcp.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"other": "preserved", "mcpServers": {"github": {"url": "https://github.example/mcp"}}}), encoding="utf-8")
        outputs = project_config(self.target, "cursor", "https://mcp.example/mcp", "sample-project", True)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_changes(outputs, dry_run=False, target_root=self.target)
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["other"], "preserved")
        self.assertIn("github", config["mcpServers"])
        self.assertIn("evidence", config["mcpServers"])

    def test_existing_protocol_requires_explicit_central_link_confirmation(self):
        (self.target / "EVIDENCE_PROTOCOL.md").write_text("local protocol\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "confirm that this slug"):
            project_config(self.target, "cursor", "https://mcp.example/mcp", "sample-project", False)
        outputs = project_config(self.target, "cursor", "https://mcp.example/mcp", "sample-project", True)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_changes(outputs, dry_run=False, target_root=self.target)
        self.assertEqual((self.target / "EVIDENCE_PROTOCOL.md").read_text(encoding="utf-8"), "local protocol\n")
        manifest = json.loads((self.target / ".evidence/project.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["local_protocol_export_present"])

    def test_rejects_insecure_or_secret_bearing_service_urls(self):
        for url, slug in (
            ("http://mcp.example/mcp", "sample-project"),
            ("https://user:secret@mcp.example/mcp", "sample-project"),
            ("https://mcp.example/mcp?token=secret", "sample-project"),
            ("https://mcp.example/mcp", "Invalid_Slug"),
        ):
            with self.subTest(url=url, slug=slug), self.assertRaises(ValueError):
                project_config(self.target, "claude", url, slug, True)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_standalone_rule_conflicts_abort_central_install(self):
        artifacts = {
            "claude": ("CLAUDE.md", "See EVIDENCE_PROTOCOL.md for current phase."),
            "devin": (".windsurf/rules/evidence.md", "local evidence rules"),
            "codex": ("AGENTS.md", "Read EVIDENCE_PROTOCOL.md first."),
            "cursor": (".cursor/rules/evidence.mdc", "local evidence rules"),
            "trae": (".trae/rules/evidence.md", "local evidence rules"),
        }
        for client, (relative, content) in artifacts.items():
            with self.subTest(client=client), tempfile.TemporaryDirectory() as temp:
                target = Path(temp)
                artifact = target / relative
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "standalone Evidence guidance"):
                    project_config(target, client, "https://mcp.example/mcp", "sample-project", True)
                self.assertFalse((target / ".evidence/project.json").exists())

    def test_invalid_config_aborts_before_other_project_files_are_written(self):
        config = self.target / ".cursor/mcp.json"
        config.parent.mkdir()
        config.write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            project_config(self.target, "cursor", "https://mcp.example/mcp", "sample-project", True)
        self.assertEqual(set(self.target.rglob("*")), {config.parent, config})

    def test_symlink_cannot_redirect_install_outside_target(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.target / ".cursor").symlink_to(outside, target_is_directory=True)
            outputs = project_config(self.target, "cursor", "https://mcp.example/mcp", "sample-project", True)
            with self.assertRaisesRegex(ValueError, "outside target"):
                apply_changes(outputs, dry_run=False, target_root=self.target)
            self.assertEqual(list(Path(outside).iterdir()), [])
            self.assertFalse((self.target / ".evidence/project.json").exists())

    def test_server_bundle_is_self_hosted_and_does_not_create_secrets(self):
        outputs = server_config(self.target)
        names = {path.relative_to(self.target / "evidence-server").as_posix() for path in outputs}
        for needed in ("method/service/markdown_view.py", "method/service/static/logo.png", "compose.keycloak.yaml"):
            self.assertIn(needed, names)
        self.assertFalse([n for n in names if "test_" in n or n.endswith(".md")])
        self.assertIn(self.target / "evidence-server" / "compose.yaml", outputs)
        self.assertIn(self.target / "evidence-server" / "Dockerfile", outputs)
        compose = outputs[self.target / "evidence-server" / "compose.yaml"]
        self.assertIn("context: .", compose)
        self.assertNotIn("internal: true", compose)
        self.assertIn(self.target / "evidence-server" / ".env.example", outputs)
        self.assertNotIn(self.target / "evidence-server" / ".env", outputs)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_changes(outputs, dry_run=True, target_root=self.target)
        self.assertEqual(list(self.target.iterdir()), [])
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            with contextlib.redirect_stdout(io.StringIO()):
                apply_changes(server_config(target), dry_run=False, target_root=target)
            installed = target / "evidence-server"
            self.assertTrue((installed / "Dockerfile").is_file())
            self.assertTrue((installed / "method/service/remote_mcp_server.py").is_file())
            self.assertFalse((installed / ".env").exists())
            if shutil.which("docker"):
                env = os.environ.copy()
                env.update({
                    "PGDATABASE": "evidence_test",
                    "PGUSER": "evidence_test",
                    "PGPASSWORD": "test-only",
                    "KC_DB_PASSWORD": "identity-test-only",
                    "EVIDENCE_PGHOST": "database",
                    "KEYCLOAK_PGHOST": "identity-database",
                    "EVIDENCE_PGDATABASE": "evidence_test",
                    "EVIDENCE_PGUSER": "evidence_test",
                    "EVIDENCE_PGPASSWORD": "test-only",
                    "KEYCLOAK_PGDATABASE": "identity_test",
                    "KEYCLOAK_PGUSER": "identity_test",
                    "KEYCLOAK_PGPASSWORD": "identity-test-only",
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "admin-test-only",
                    "OIDC_PUBLIC_URL": "https://identity.example.test",
                    "MCP_PUBLIC_URL": "https://mcp.example.test/mcp",
                    "MCP_ALLOWED_HOSTS": "mcp.example.test,mcp.example.test:443",
                    "MCP_ALLOWED_ORIGINS": "",
                })
                result = subprocess.run(
                    ["docker", "compose", "-f", str(installed / "compose.yaml"), "config", "--quiet"],
                    cwd=installed,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_token_env_references_variable_and_never_embeds_a_token(self):
        with tempfile.TemporaryDirectory() as temp:
            for agent in ("claude", "devin", "codex", "cursor", "trae"):
                outputs = project_config(Path(temp), agent, "https://evidence.example/mcp", "demo-project", True, "EVIDENCE_TOKEN")
                text = "\n".join(outputs.values())
                self.assertIn("EVIDENCE_TOKEN", text, agent)
                self.assertNotIn("evk_", text, agent)
            with self.assertRaises(ValueError):
                project_config(Path(temp), "claude", "https://evidence.example/mcp", "demo-project", True, "bad name")


    def test_join_dry_run_never_contacts_the_service(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "-C", temp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", temp, "remote", "add", "origin", "https://git.example.com/acme/demo.git"], check=True)
            base = ["python3", "evidence_install.py", "join", "--target", temp, "--agent", "claude",
                    "--service-url", "http://127.0.0.1:1/mcp"]  # nothing listens on port 1
            env = {k: v for k, v in os.environ.items() if k != "EVIDENCE_TOKEN"}
            dry = subprocess.run(base + ["--dry-run"], capture_output=True, text=True, timeout=30, env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)  # no token set and no server: it must still preview
            self.assertIn("NOT contacted", dry.stdout)
            self.assertIn("Dry run only; no files were written.", dry.stdout)
            self.assertEqual([p.name for p in Path(temp).iterdir()], [".git"])
            real = subprocess.run(base, capture_output=True, text=True, timeout=30, env={**env, "EVIDENCE_TOKEN": "evk_test"})
            self.assertNotEqual(real.returncode, 0)  # the real run does contact the service
            self.assertIn("cannot reach service", real.stderr)

    def test_service_calls_identify_the_installer_instead_of_the_default_python_user_agent(self):
        import io
        import evidence_install
        seen = {}
        original = evidence_install.urllib.request.urlopen
        evidence_install.urllib.request.urlopen = lambda req, timeout=0: (seen.update(ua=req.get_header("User-agent")), io.BytesIO(b"{}"))[1]
        try:
            evidence_install.call_service("https://service.example/api/join", "evk_x", {"join_key": "a/b"})
        finally:
            evidence_install.urllib.request.urlopen = original
        self.assertEqual(seen["ua"], "evidence-installer/1.0")  # never Python-urllib, which CDNs commonly block

if __name__ == "__main__":
    unittest.main()
