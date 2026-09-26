#!/usr/bin/env bash
# Install the scientific method's Codex hooks globally.
set -euo pipefail

CODEX_DIR="${CODEX_DIR:-$HOME/.codex}"
HOOKS_DIR="$CODEX_DIR/hooks"
DOCS_DIR="$CODEX_DIR/scientific-method"
HOOKS_CONFIG="$CODEX_DIR/hooks.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METHOD_DIR="$(cd "$SCRIPT_DIR/../method" && pwd)"
mkdir -p "$HOOKS_DIR" "$DOCS_DIR"

for doc in SCIENTIFIC_METHOD.md ENFORCEMENT_MODEL.md; do
  source="$METHOD_DIR/$doc"
  dest="$DOCS_DIR/$doc"
  if [ -f "$dest" ] && ! diff -q "$source" "$dest" >/dev/null 2>&1; then
    echo "WARNING: $dest differs from this package; preserving it. Review manually." >&2
  else
    cp "$source" "$dest"
    echo "OK  $dest"
  fi
done

for script in session-start-protocol-global.sh protocol-header.sh; do
  cp "$SCRIPT_DIR/hooks/$script" "$HOOKS_DIR/$script"
  chmod +x "$HOOKS_DIR/$script"
  echo "OK  $HOOKS_DIR/$script"
done

[ -f "$HOOKS_CONFIG" ] || printf '{"hooks":{}}\n' > "$HOOKS_CONFIG"
SESSION_CMD="bash '$HOOKS_DIR/session-start-protocol-global.sh'"
HEADER_CMD="bash '$HOOKS_DIR/protocol-header.sh' hook"
TMP="$(mktemp "${HOOKS_CONFIG}.XXXXXX")"
python3 - "$HOOKS_CONFIG" "$TMP" "$SESSION_CMD" "$HEADER_CMD" <<'PY'
import json, sys
src, dst, session_cmd, header_cmd = sys.argv[1:]
with open(src, encoding="utf-8") as f:
    config = json.load(f)
hooks = config.setdefault("hooks", {})

def add(event, command, status=None):
    groups = hooks.setdefault(event, [])
    if any(h.get("command") == command for group in groups for h in group.get("hooks", [])):
        return
    handler = {"type": "command", "command": command, "timeout": 15}
    if status:
        handler["statusMessage"] = status
    group = {"hooks": [handler]}
    if event in ("PreToolUse", "PostToolUse"):
        group["matcher"] = ""
    groups.append(group)

add("SessionStart", session_cmd, "Loading scientific method protocol...")
add("UserPromptSubmit", header_cmd)
add("PostToolUse", header_cmd)
with open(dst, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
mv "$TMP" "$HOOKS_CONFIG"
echo "OK  $HOOKS_CONFIG (SessionStart, UserPromptSubmit, and PostToolUse hooks registered)"
echo "Restart Codex or start a new session, then use /hooks to review and trust the hooks."
