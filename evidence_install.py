from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import subprocess
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
import urllib.parse
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
MARKER_START = "<!-- evidence-central:start -->"
MARKER_END = "<!-- evidence-central:end -->"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,62})[a-z0-9]$")


def reject_standalone_guidance(target: Path, client: str) -> None:
    known_rules = {
        "devin": [target / ".windsurf/rules/evidence.md"],
        "cursor": [target / ".cursor/rules/evidence.mdc"],
        "trae": [target / ".trae/rules/evidence.md"],
    }
    conflicts = [path for path in known_rules.get(client, []) if path.is_file()]
    if client == "claude":
        for path in (target / "CLAUDE.md", target / ".claude/rules/evidence.md", target / ".claude/rules/evidence.mdc"):
            if path.is_file() and "EVIDENCE_PROTOCOL.md" in path.read_text(encoding="utf-8"):
                conflicts.append(path)
    if client == "codex":
        path = target / "AGENTS.md"
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if MARKER_START in text and MARKER_END in text:
                start = text.index(MARKER_START)
                end = text.index(MARKER_END, start) + len(MARKER_END)
                text = text[:start] + text[end:]
            if "EVIDENCE_PROTOCOL.md" in text:
                conflicts.append(path)
    if conflicts:
        paths = ", ".join(str(path) for path in conflicts)
        raise ValueError(f"standalone Evidence guidance conflicts with central source of truth: {paths}; review and remove/convert it before central installation")


def project_config(target: Path, client: str, server_url: str, slug: str, confirmed: bool,
                   token_env: str | None = None) -> dict[Path, str]:
    manifest = target / ".evidence" / "project.json"
    protocol = target / "EVIDENCE_PROTOCOL.md"
    if not confirmed:
        raise ValueError("confirm that this slug is provisioned centrally; import/reconcile any local protocol first")
    parsed_url = urlparse(server_url)
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("project slug must be lowercase alphanumeric with internal hyphens")
    if parsed_url.scheme != "https" and not (
        parsed_url.scheme == "http" and parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("service URL must use HTTPS except for loopback development URLs")
    if not parsed_url.netloc or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
        raise ValueError("service URL must not contain credentials, query parameters, or a fragment")
    reject_standalone_guidance(target, client)
    outputs: dict[Path, str] = {
        manifest: json.dumps(
            {
                "service_url": server_url,
                "project_slug": slug,
                "protocol_source": "central",
                "local_protocol_export_present": protocol.exists(),
            },
            indent=2,
        ) + "\n"
    }
    entries = {
        "claude": (target / ".mcp.json", {"type": "http", "url": server_url}),
        "devin": (target / ".devin" / "mcp_config.json", {"url": server_url}),
        "codex": (target / ".codex" / "config.toml", {"url": server_url, "auth": "oauth"}),
        "cursor": (target / ".cursor" / "mcp.json", {"url": server_url}),
        "trae": (target / ".trae" / "mcp.json", {"url": server_url}),
    }
    config_path, entry = entries[client]
    if token_env:  # per-user token: reference the env var by name, never write the token itself
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", token_env):
            raise ValueError("token env var name must be UPPER_SNAKE_CASE")
        bearer = {"claude": "${%s}", "devin": "${env:%s}", "cursor": "${env:%s}", "trae": "${env:%s}"}
        if client == "codex":
            entry = {"url": server_url, "bearer_token_env_var": token_env}
        else:
            entry = {**entry, "headers": {"Authorization": "Bearer " + bearer[client] % token_env}}
    if client == "codex":
        outputs[config_path] = merge_codex(config_path, entry)
    else:
        outputs[config_path] = merge_json_config(config_path, entry)
    instructions = make_instructions(client, slug, server_url)
    if client == "claude":
        outputs[target / ".claude" / "rules" / "evidence-central.md"] = instructions
    elif client == "devin":
        outputs[target / ".windsurf" / "rules" / "evidence-central.md"] = instructions
    elif client == "codex":
        agents = target / "AGENTS.md"
        outputs[agents] = merge_managed_section(agents, instructions)
    elif client == "cursor":
        outputs[target / ".cursor" / "rules" / "evidence-central.mdc"] = (
            "---\ndescription: Evidence central protocol\nalwaysApply: true\n---\n\n" + instructions
        )
    else:
        outputs[target / ".trae" / "rules" / "evidence-central.md"] = (
            "---\nalwaysApply: true\n---\n\n" + instructions
        )
    return outputs


def make_instructions(client: str, slug: str, server_url: str) -> str:
    body = (
        f"# Evidence central protocol\n\n"
        f"The authoritative protocol is stored in the Evidence service, not in a local Markdown copy.\n"
        f"Project slug: `{slug}`. MCP service: `{server_url}`.\n\n"
        "Before acting, call the `evidence` MCP server's `protocol_header` tool with this project slug. "
        "Use `protocol_get` for the full body and `protocol_search` for hypotheses, incidents, and phases. "
        "For edits, call `protocol_update` with the revision you read; stop and reread if it reports a conflict. "
        "Do not treat a local EVIDENCE_PROTOCOL.md export as authoritative.\n"
    )
    if client == "codex":
        return f"{MARKER_START}\n{body}{MARKER_END}\n"
    if client == "devin":
        return "---\ntrigger: always_on\n---\n\n" + body
    return body


def merge_json_config(path: Path, entry: dict) -> str:
    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"refusing to modify invalid JSON config {path}: {exc}") from exc
        if not isinstance(config, dict):
            raise ValueError(f"refusing to modify non-object JSON config {path}")
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"mcpServers in {path} is not an object")
    existing = servers.get("evidence")
    if existing is not None and existing != entry:
        raise ValueError(f"an incompatible MCP server named 'evidence' already exists in {path}")
    servers["evidence"] = entry
    return json.dumps(config, indent=2) + "\n"


def merge_codex(path: Path, entry: dict[str, str]) -> str:
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        config = tomllib.loads(existing_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"refusing to modify invalid TOML config {path}: {exc}") from exc
    existing = config.get("mcp_servers", {}).get("evidence")
    if existing is not None:
        same_auth = (existing.get("bearer_token_env_var") == entry["bearer_token_env_var"] if "bearer_token_env_var" in entry
                     else "bearer_token_env_var" not in existing and existing.get("auth", "oauth") == entry["auth"])
        if existing.get("url") == entry["url"] and same_auth:
            return existing_text
        raise ValueError(f"an incompatible MCP server named 'evidence' already exists in {path}")
    separator = "" if not existing_text or existing_text.endswith("\n\n") else "\n" if existing_text.endswith("\n") else "\n\n"
    return existing_text + separator + (
        "[mcp_servers.evidence]\n"
        f"url = {json.dumps(entry['url'])}\n"
        + (f"bearer_token_env_var = {json.dumps(entry['bearer_token_env_var'])}\n" if "bearer_token_env_var" in entry
           else f"auth = {json.dumps(entry['auth'])}\n")
        + "enabled = true\n"
    )


def merge_managed_section(path: Path, section: str) -> str:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start_count, end_count = existing.count(MARKER_START), existing.count(MARKER_END)
    if start_count != end_count or start_count > 1:
        raise ValueError(f"managed Evidence section markers are malformed in {path}")
    if start_count:
        start = existing.index(MARKER_START)
        end = existing.index(MARKER_END, start) + len(MARKER_END)
        return existing[:start] + section.rstrip() + existing[end:]
    return existing.rstrip() + ("\n\n" if existing.strip() else "") + section


def server_bundle() -> dict[str, str | bytes]:
    service = ROOT / "method/service"
    paths = ["method/__init__.py", "method/protocol-header.sh", "method/protocol-search.sh"]
    paths += sorted(
        str(f.relative_to(ROOT)) for f in service.rglob("*")
        if f.is_file() and "__pycache__" not in f.parts and f.suffix in {".py", ".sql", ".css", ".png"} | {""}
        and not f.name.startswith("test_") and f.name not in {"compose.yaml", "Dockerfile"}
    ) + ["method/service/requirements.txt"]
    bundle: dict[str, str | bytes] = {}
    for relative in dict.fromkeys(paths):
        data = (ROOT / relative).read_bytes()
        bundle[relative] = data if relative.endswith(".png") else data.decode("utf-8")
    bundle["Dockerfile"] = (service / "Dockerfile").read_text(encoding="utf-8")
    for name in ("compose.yaml", "compose.keycloak.yaml"):
        text = (service / name).read_text(encoding="utf-8")
        bundle[name] = text.replace("context: ../..\n      dockerfile: method/service/Dockerfile", "context: .\n      dockerfile: Dockerfile")
    bundle[".env.example"] = (service / ".env.example").read_text(encoding="utf-8")
    return bundle


def server_config(target: Path) -> dict[Path, str | bytes]:
    destination = target / "evidence-server"
    return {destination / relative: content for relative, content in server_bundle().items()}


def apply_changes(outputs: dict[Path, str | bytes], dry_run: bool, target_root: Path) -> None:
    root = target_root.resolve(strict=True)
    changes = []
    for path, content in outputs.items():
        if not path.resolve(strict=False).is_relative_to(root):
            raise ValueError(f"refusing to write outside target directory: {path}")
        if path.is_symlink():
            raise ValueError(f"refusing to modify symlink {path}")
        if path.exists():
            if not path.is_file():
                raise ValueError(f"refusing to replace non-file path {path}")
            current = path.read_bytes() if isinstance(content, bytes) else path.read_text(encoding="utf-8")
            if current == content:
                continue
            if path.name not in {".mcp.json", "mcp.json", "mcp_config.json", "config.toml", "AGENTS.md"}:
                raise ValueError(f"refusing to overwrite existing file with different content: {path}")
            changes.append((path, content, "UPDATE"))
        else:
            changes.append((path, content, "CREATE"))
    for path, _, action in changes:
        print(f"{action} {path}")
    if dry_run:
        return
    staged: list[tuple[Path, Path]] = []
    try:
        for path, content, _ in changes:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.resolve(strict=False).is_relative_to(root) or path.is_symlink():
                raise ValueError(f"refusing to write outside target directory: {path}")
            mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "wb" if isinstance(content, bytes) else "w", **({} if isinstance(content, bytes) else {"encoding": "utf-8"})) as stream:
                stream.write(content)
            os.chmod(tmp_name, mode)
            staged.append((Path(tmp_name), path))
        for temp_path, path in staged:
            action = "UPDATED" if any(changed_path == path and kind == "UPDATE" for changed_path, _, kind in changes) else "CREATED"
            os.replace(temp_path, path)
            print(f"{action} {path}")
    finally:
        for temp_path, _ in staged:
            if temp_path.exists():
                temp_path.unlink()


def existing_directory(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"target is not a directory: {path}")
    return path


def check_service_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("service URL must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("non-local service URLs must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("service URL must not contain credentials, query parameters, or a fragment")
    return value.rstrip("/")


def service_origin(mcp_url: str) -> str:
    return mcp_url.removesuffix("/mcp")


def read_token(env_name: str) -> str:
    token = os.environ.get(env_name, "")
    if not token:
        raise ValueError(f"set {env_name} to your Evidence user token (it is never written to disk or printed)")
    return token


def call_service(url: str, token: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode(),
        # A named client: some CDNs/WAFs in front of the service reject the default Python-urllib User-Agent.
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "evidence-installer/1.0"},
        method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # message only: never echo response bodies, they may hold secrets
        raise ValueError(f"service returned HTTP {exc.code} for {urlparse(url).path}") from None
    except urllib.error.URLError as exc:
        raise ValueError(f"cannot reach service: {exc.reason}") from None


def git_join_key(target: Path) -> str:
    done = subprocess.run(["git", "-C", str(target), "remote", "get-url", "origin"],
                          capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        raise ValueError("no git origin remote; pass --join-key explicitly (for example host/org/repo)")
    return done.stdout.strip()


def run_with_secrets(target: Path, command: list[str], token_env: str) -> int:
    manifest = json.loads((target / ".evidence" / "project.json").read_text(encoding="utf-8"))
    url = check_service_url(manifest["service_url"])
    query = urllib.parse.urlencode({"project": manifest["project_slug"]})
    secrets_env = call_service(f"{service_origin(url)}/api/vault/env?{query}", read_token(token_env))
    if not command:
        raise ValueError("give a command after --, for example: run --target . -- ./deploy.sh")
    print(f"evidence: injecting {len(secrets_env)} secret(s) as environment variables", file=sys.stderr)
    return subprocess.run(command, env={**os.environ, **secrets_env}).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="evidence-install")
    commands = parser.add_subparsers(dest="mode", required=True)
    project = commands.add_parser("project")
    project.add_argument("--target", required=True, type=existing_directory)
    project.add_argument("--agent", required=True, choices=("claude", "devin", "codex", "cursor", "trae"))
    project.add_argument("--service-url", required=True)
    project.add_argument("--project-slug", required=True)
    project.add_argument("--confirm-project-linked", action="store_true", required=True)
    project.add_argument("--dry-run", action="store_true")
    join = commands.add_parser("join", help="register this repository with the service using your user token")
    join.add_argument("--target", required=True, type=existing_directory)
    join.add_argument("--agent", required=True, choices=("claude", "devin", "codex", "cursor", "trae"))
    join.add_argument("--service-url", required=True)
    join.add_argument("--join-key", help="repository identifier; default: git origin remote")
    join.add_argument("--name", help="project name if it must be created; default: repository name")
    join.add_argument("--token-env", default="EVIDENCE_TOKEN")
    join.add_argument("--dry-run", action="store_true")
    run = commands.add_parser("run", help="run a command with the secrets you may read as env vars")
    run.add_argument("--target", type=existing_directory, default=Path.cwd())
    run.add_argument("--token-env", default="EVIDENCE_TOKEN")
    run.add_argument("command", nargs=argparse.REMAINDER)
    server = commands.add_parser("server")
    server.add_argument("--target", required=True, type=existing_directory)
    server.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.mode == "project":
            parsed = urlparse(args.service_url)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                raise ValueError("service URL must be an absolute HTTP(S) URL")
            if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("non-local service URLs must use HTTPS")
            if not SLUG_RE.fullmatch(args.project_slug):
                raise ValueError("project slug must be 3-64 lowercase letters, digits, or hyphens")
            outputs = project_config(
                args.target,
                args.agent,
                args.service_url.rstrip("/"),
                args.project_slug,
                args.confirm_project_linked,
            )
        elif args.mode == "join":
            service = check_service_url(args.service_url)
            join_key = args.join_key or git_join_key(args.target)
            name = args.name or join_key.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            reject_standalone_guidance(args.target, args.agent)  # fail before the service is touched, never half-way
            local = args.target / "EVIDENCE_PROTOCOL.md"
            protocol = local.read_text(encoding="utf-8") if local.is_file() and local.stat().st_size <= 2_000_000 else None
            payload = {"join_key": join_key, "name": name}
            if protocol and protocol.strip():
                payload["protocol"] = protocol
            result = call_service(f"{service_origin(service)}/api/join", read_token(args.token_env), payload)
            print(f"{'Created' if result['created'] else 'Joined'} project {result['project_slug']} as {result['role']}")
            if result.get("imported_protocol"):
                print("Imported the local EVIDENCE_PROTOCOL.md as the first revision of the central protocol.")
            elif protocol and not result["created"]:
                print("Note: the project already existed, so the local EVIDENCE_PROTOCOL.md was NOT imported. "
                      "The central copy wins; compare it with the local file in the web UI and update it there if needed.")
            outputs = project_config(args.target, args.agent, service, result["project_slug"], True, args.token_env)
        elif args.mode == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return run_with_secrets(args.target, command, args.token_env)
        else:
            outputs = server_config(args.target)
        apply_changes(outputs, args.dry_run, args.target)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print("Dry run only; no files were written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
