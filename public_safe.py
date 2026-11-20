#!/usr/bin/env python3
"""Refuse instance-specific details in anything that could reach this public repo.

Modes (used by .githooks and the test):
  --worktree       every tracked or not-ignored file on disk
  --staged         the staged version of each changed file (pre-commit)
  --message FILE   a commit message (commit-msg)
  --push           commits about to be pushed, read from pre-push's stdin: messages and added lines
Findings name the file and the rule, never the matched text. Private strings of your own (real domain, hostnames,
project ids) go one per line in the gitignored `.public-safe-deny` and are matched case-insensitively.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATTERNS = {
    "private IP (use 192.168.50.x for examples)": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.(?!50\.)\d{1,3}\.\d{1,3})\b"),
    "ssh user@host": re.compile(r"\bssh\s+[a-z_][\w-]*@\S+", re.I),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "private notes file": re.compile(r"access\.md"),
    "internal hostname": re.compile(r"\bsrv\d{2}\b"),
    "env-style credential": re.compile(r"^\s*[A-Z][A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[ \t]*=[ \t]*(?!(?i:replace|change|example|your|placeholder|dummy|test))[^\s#<$'\"{][^\s]{7,}", re.M),
    "known token format": re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16}|GOCSPX-[A-Za-z0-9_-]{20,}|evk_[A-Za-z0-9_-]{30,})"),
}
# These three hold the rule definitions, test fixtures, or deliberately name the ignored private files.
EXEMPT = {".gitignore", "public_safe.py", "test_public_safe.py"}


def git(*args: str, text: bool = True) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True, text=text).stdout


def rules() -> list[tuple[str, re.Pattern]]:
    deny = ROOT / ".public-safe-deny"
    extra = [(("private deny-list entry"), re.compile(re.escape(line.strip()), re.I))
             for line in (deny.read_text().splitlines() if deny.exists() else [])
             if line.strip() and not line.startswith("#")]
    return [*PATTERNS.items(), *extra]


def scan(label: str, text: str) -> list[str]:
    return [f"{label}: {name}" for name, pattern in rules() if pattern.search(text)]


def worktree() -> list[str]:
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    hits = []
    for name in filter(None, names):
        path = ROOT / name
        if name in EXEMPT or not path.is_file():
            continue
        try:
            hits += scan(name, path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            pass
    return hits


def staged() -> list[str]:
    hits = []
    for name in filter(None, git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")):
        if name in EXEMPT:
            continue
        try:
            hits += scan(name, git("show", f":{name}"))
        except (subprocess.CalledProcessError, UnicodeDecodeError):
            pass
    return hits


def commits_in_push(stdin_lines: list[str]) -> list[str]:
    shas: list[str] = []
    for line in stdin_lines:
        _, local, _, remote = (line.split() + ["", "", "", ""])[:4]
        if not local.strip("0"):  # deleting a ref
            continue
        spec = [local] if not remote.strip("0") else [f"{remote}..{local}"]
        args = ["rev-list", *spec] + (["--not", "--remotes"] if not remote.strip("0") else [])
        shas += git(*args).split()
    return list(dict.fromkeys(shas))


def push(stdin_lines: list[str]) -> list[str]:
    hits = []
    for sha in commits_in_push(stdin_lines):
        hits += scan(f"commit {sha[:10]} message", git("log", "-1", "--format=%B", sha))
        exempt = [f":(exclude){name}" for name in sorted(EXEMPT)]
        added = "\n".join(line[1:] for line in git("show", "--format=", "-U0", sha, "--", ".", *exempt).splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        for name, pattern in rules():
            if pattern.search(added):
                hits.append(f"commit {sha[:10]} content: {name}")
    return hits


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--worktree"
    hits = {"--worktree": worktree, "--staged": staged}.get(mode, lambda: [])()
    if mode == "--message":
        hits = scan("commit message", Path(argv[2]).read_text(encoding="utf-8"))
    elif mode == "--push":
        hits = push(sys.stdin.read().splitlines())
    if hits:
        print("PUBLIC-SAFE: blocked, instance-specific details found (matched text not shown):", file=sys.stderr)
        for hit in dict.fromkeys(hits):
            print(f"  - {hit}", file=sys.stderr)
        print("Move them to .env / private/ or replace with placeholders. Bypassing with --no-verify is not allowed here.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
