#!/usr/bin/env bash
# Sets up Codex CLI delivery for this method: per-project (AGENTS.md is
# Codex's confirmed, tested mechanism — see README.md) plus the optional
# service-mode MCP server, registered globally so every trusted project can
# call it.
#
# What this script deliberately does NOT do: mark any project "trusted" in
# ~/.codex/config.toml. Trust also gates project-local sandbox/approval
# config, so a malicious .codex/config.toml in a cloned repo could otherwise
# use it to weaken your sandbox — that is a security decision for you to
# make per project, not something an install script should do on your
# behalf. Codex will prompt you for it interactively the first time you run
# it inside a project; do it there, or add the block this script prints.
#
# Usage: ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METHOD_DIR="$(cd "$SCRIPT_DIR/../method" && pwd)"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
DOCS_DIR="$CODEX_DIR/scientific-method"

mkdir -p "$DOCS_DIR"

# 1. Copy the canonical docs for reference — Codex has no confirmed
#    machine-wide "read this on every session" hook (see README.md), so this
#    is reference material for whoever sets up AGENTS.md or the optional
#    hooks.json, not something Codex reads on its own.
for doc in SCIENTIFIC_METHOD.md ENFORCEMENT_MODEL.md; do
  dest="$DOCS_DIR/$doc"
  if [ -f "$dest" ] && ! diff -q "$METHOD_DIR/$doc" "$dest" >/dev/null 2>&1; then
    echo "WARNING: $dest already exists and differs from this package — not overwriting."
  else
    cp "$METHOD_DIR/$doc" "$dest"
    echo "OK  $dest"
  fi
done

# 2. Register the service-mode MCP server globally, via Codex's own `codex
#    mcp add` — confirmed idempotent (re-running updates the entry in place,
#    does not duplicate it) and it only ever touches the mcp_servers table,
#    never trust/sandbox config.
if command -v codex >/dev/null 2>&1; then
  codex mcp add scientific-method -- python3 "$METHOD_DIR/service/protocol_mcp_server.py"
  echo "OK  registered MCP server 'scientific-method' (codex mcp get scientific-method to inspect)"
else
  cat <<EOF
NOTE: 'codex' was not found on PATH, so the MCP server was not registered.
Once Codex CLI is installed, run:
  codex mcp add scientific-method -- python3 "$METHOD_DIR/service/protocol_mcp_server.py"
EOF
fi

echo
cat <<EOF
Done. Two things this script did NOT do, on purpose:

1. Write an AGENTS.md for any specific project. Copy
   $SCRIPT_DIR/AGENTS.md.template to <project>/AGENTS.md and fill it in —
   Codex reads it automatically, but ONLY for a trusted project (see 2).

2. Mark any project trusted. Confirmed against a real Codex CLI 0.157.1
   install: an untrusted project gets none of AGENTS.md's content, with no
   error or warning. Either answer "trust this folder" the first time you
   run 'codex' inside the project, or add this yourself to
   $CODEX_DIR/config.toml:

     [projects."/absolute/path/to/project"]
     trust_level = "trusted"

See README.md for what was independently verified vs. what is still
documentation-only, including why this script does not install a
SessionStart hooks.json entry.
EOF
