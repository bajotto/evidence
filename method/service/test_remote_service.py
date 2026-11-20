from __future__ import annotations

import asyncio
import os
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.provider import AccessToken, TokenVerifier
from psycopg.conninfo import conninfo_to_dict
from starlette.testclient import TestClient

from method.service.oidc import OidcTokenVerifier
from method.service.remote_mcp_server import _protocol_file, _store, _validated_url, create_server
from method.service.store import Store

ROOT = Path(__file__).resolve().parents[2]
CONNINFO = os.environ.get("EVIDENCE_TEST_CONNINFO")


class OidcVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.verifier = OidcTokenVerifier(
            "https://issuer.example", "https://issuer.example/keys", "evidence-mcp"
        )
        self.verifier.jwks = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=self.private_key.public_key())
        )

    def token(self, **overrides):
        claims = {
            "iss": "https://issuer.example",
            "aud": "evidence-mcp",
            "sub": "user-123",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "scope": "evidence:access evidence:admin",
            "email": "user@example.com",
            "email_verified": True,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test"})

    def test_accepts_valid_issuer_audience_and_subject(self):
        access = asyncio.run(self.verifier.verify_token(self.token()))
        self.assertIsNotNone(access)
        self.assertEqual(access.subject, "user-123")
        self.assertEqual(access.scopes, ["evidence:access", "evidence:admin"])
        self.assertEqual(access.claims["email"], "user@example.com")

    def test_rejects_wrong_issuer_audience_and_expiration(self):
        for claims in (
            {"iss": "https://attacker.example"},
            {"aud": "different-service"},
            {"exp": int(time.time()) - 60},
        ):
            with self.subTest(claims=claims):
                self.assertIsNone(asyncio.run(self.verifier.verify_token(self.token(**claims))))

    def test_rejects_non_rs256_algorithm(self):
        token = jwt.encode(
            {"iss": "https://issuer.example", "aud": "evidence-mcp", "sub": "user-123", "iat": int(time.time()), "exp": int(time.time()) + 600},
            "test-only-secret-with-at-least-32-bytes",
            algorithm="HS256",
        )
        self.assertIsNone(asyncio.run(self.verifier.verify_token(token)))


class UrlValidationTests(unittest.TestCase):
    def test_only_https_or_explicit_local_identity_urls_are_accepted(self):
        self.assertEqual(
            _validated_url("http://identity:8080/keys", "jwks", allow_identity_service=True),
            "http://identity:8080/keys",
        )
        self.assertEqual(
            _validated_url("http://127.0.0.1:9000/keys", "jwks", allow_loopback=True),
            "http://127.0.0.1:9000/keys",
        )
        self.assertEqual(
            _validated_url("http://localhost:8081/realms/evidence", "issuer", allow_loopback=True),
            "http://localhost:8081/realms/evidence",
        )
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            _validated_url("http://issuer.example/realms/evidence", "issuer", allow_loopback=True)

    def test_private_http_only_with_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            _validated_url("http://192.168.50.10:9000/realms/evidence", "issuer")
        self.assertEqual(
            _validated_url("http://192.168.50.10:9000/realms/evidence", "issuer", allow_private=True),
            "http://192.168.50.10:9000/realms/evidence",
        )
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            _validated_url("http://8.8.8.8/realms/evidence", "issuer", allow_private=True)

    def test_private_http_flag_unlocks_lan_server(self):
        env = {
            "MCP_OIDC_ISSUER_URL": "http://192.168.50.10:9000/realms/evidence",
            "MCP_OIDC_JWKS_URL": "http://identity:8080/realms/evidence/protocol/openid-connect/certs",
            "MCP_OIDC_AUDIENCE": "evidence-mcp",
            "MCP_PUBLIC_URL": "http://192.168.50.10:8000/mcp",
            "MCP_ALLOWED_HOSTS": "192.168.50.10:8000",
            "MCP_INSECURE_PRIVATE_HTTP": "true",
        }
        with patch.dict(os.environ, env):
            server = create_server(Store(""), StaticTestVerifier())
        self.assertIsNotNone(server)
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            _validated_url("http://database:5432/keys", "jwks", allow_identity_service=True)
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            _validated_url("http://identity:8081/keys", "jwks", allow_identity_service=True)


class OptionalOidcTests(unittest.TestCase):
    def test_server_starts_without_oidc_and_rejects_non_user_tokens(self):
        from method.service.oidc import CompositeTokenVerifier
        env = {"MCP_PUBLIC_URL": "https://mcp.example.test/mcp", "MCP_ALLOWED_HOSTS": "mcp.example.test"}
        with patch.dict(os.environ, env):
            os.environ.pop("MCP_OIDC_ISSUER_URL", None)
            self.assertIsNotNone(create_server(Store(""), None))
        verifier = CompositeTokenVerifier(None, SimpleNamespace(resolve_token=lambda t: None))
        self.assertIsNone(asyncio.run(verifier.verify_token("eyJhbGciOi.not-a-user-token")))
        self.assertIsNone(asyncio.run(verifier.verify_token("evk_unknown")))


class StoreConninfoTests(unittest.TestCase):
    def test_store_conninfo_uses_valid_psycopg_options(self):
        env = {
            "PGHOST": "database",
            "PGDATABASE": "evidence",
            "PGUSER": "evidence",
            "PGPASSWORD": "secret with 'quote' and spaces",
        }
        with patch.dict(os.environ, env):
            params = conninfo_to_dict(_store().conninfo)
        self.assertEqual(params["host"], "database")
        self.assertEqual(params["dbname"], "evidence")
        self.assertEqual(params["user"], "evidence")
        self.assertEqual(params["password"], "secret with 'quote' and spaces")
        self.assertEqual(params["port"], "5432")


class ProtocolToolsTests(unittest.TestCase):
    def test_header_and_search_operate_on_temporary_protocol_copy(self):
        source = (ROOT / "method/PROJECT_PROTOCOL_TEMPLATE.md").read_text(encoding="utf-8")
        header = _protocol_file("sample-project", source, "header")
        self.assertIn("PROTOCOL-HEADER:START", header)
        self.assertIn("**Project:** [PROJECT_NAME]", header)
        phase = _protocol_file("sample-project", source, "search", "phase", "2")
        self.assertIn("Phase 2", phase)

    def test_normalize_preserves_full_body(self):
        body = "# demo — Evidence Protocol\n\nBody marker: must survive normalization.\n"
        normalized = _protocol_file("demo-project", body, "normalize")
        self.assertIn("PROTOCOL-HEADER:START", normalized)
        self.assertIn("Body marker: must survive normalization.", normalized)

    def test_slug_cannot_escape_temporary_directory(self):
        with self.assertRaisesRegex(ValueError, "invalid project slug"):
            _protocol_file("../outside", "body", "header")


class StaticTestVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "valid-test-token":
            return None
        return AccessToken(
            token=token,
            client_id="test-client",
            scopes=["evidence:access"],
            expires_at=int(time.time()) + 600,
            subject="http-test-owner",
            claims={"email": "owner@example.test"},
        )


@unittest.skipUnless(CONNINFO, "set EVIDENCE_TEST_CONNINFO to an isolated PostgreSQL test database")
class RemoteMcpHttpTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(CONNINFO)
        self.store.initialize()
        self.slug = "http-test-" + uuid.uuid4().hex[:12]
        self.store.create_project(self.slug, "HTTP test", "# HTTP test\n\nProtocol body marker.\n", "http-test-owner")

    def tearDown(self):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM projects WHERE slug = %s", (self.slug,))
            conn.execute("DELETE FROM users WHERE subject = 'http-test-owner'")

    def test_http_mcp_requires_bearer_and_reads_current_database_protocol(self):
        env = {
            "MCP_OIDC_ISSUER_URL": "https://issuer.example",
            "MCP_OIDC_AUDIENCE": "evidence-mcp",
            "MCP_PUBLIC_URL": "https://mcp.example.test/mcp",
            "MCP_ALLOWED_HOSTS": "testserver",
        }
        with patch.dict(os.environ, env):
            app = create_server(self.store, StaticTestVerifier()).streamable_http_app()
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2024-11-05",
            "Content-Type": "application/json",
        }
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            unauthenticated = client.post("/mcp", json=initialize, headers=headers)
            self.assertEqual(unauthenticated.status_code, 401)
            self.assertIn("resource_metadata=", unauthenticated.headers.get("WWW-Authenticate", ""))
            headers["Authorization"] = "Bearer valid-test-token"
            response = client.post("/mcp", json=initialize, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            tools = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers=headers,
            )
            self.assertEqual(tools.status_code, 200, tools.text)
            self.assertIn("protocol_update", tools.text)
            protocol = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "protocol_get", "arguments": {"project_slug": self.slug}},
                },
                headers=headers,
            )
            self.assertEqual(protocol.status_code, 200, protocol.text)
            self.assertIn("Protocol body marker.", protocol.text)
            seen = self.store.sync_status(self.slug, "http-test-owner")["members"][0]  # the agent's read was recorded
            self.assertEqual((seen["status"], seen["via"], seen["read_revision"]), ("current", "mcp", 1))
            status = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                               "params": {"name": "protocol_sync_status", "arguments": {"project_slug": self.slug}}},
                                 headers=headers)
            self.assertIn("synced", status.text)


if __name__ == "__main__":
    unittest.main()
