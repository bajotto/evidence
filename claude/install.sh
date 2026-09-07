#!/usr/bin/env bash
# Installs the global SessionStart hook that injects this method into
# every Claude Code session on this machine, in any project — no
# per-project configuration needed.
#
# Usage: ./install.sh
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required and was not found. Install it first:" >&2
  echo "  Debian/Ubuntu: sudo apt-get install -y jq" >&2
  echo "  macOS:         brew install jq" >&2
  exit 1
fi

CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS="$CLAUDE_DIR/settings.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METHOD_DIR="$(cd "$SCRIPT_DIR/../method" && pwd)"

mkdir -p "$HOOKS_DIR"

# 1. Copy the global docs (warn instead of overwriting if a different
#    version already exists — don't silently clobber local edits)
for doc in SCIENTIFIC_METHOD.md ENFORCEMENT_MODEL.md; do
  dest="$CLAUDE_DIR/$doc"
  if [ -f "$dest" ] && ! diff -q "$METHOD_DIR/$doc" "$dest" >/dev/null 2>&1; then
    echo "WARNING: $dest already exists and differs from this package — not overwriting."
    echo "         Review manually: diff '$METHOD_DIR/$doc' '$dest'"
  else
    cp "$METHOD_DIR/$doc" "$dest"
    echo "OK  $dest"
  fi
done

# 2. Copy the hook script and supporting scripts
cp "$SCRIPT_DIR/hooks/session-start-protocol-global.sh" "$HOOKS_DIR/session-start-protocol-global.sh"
chmod +x "$HOOKS_DIR/session-start-protocol-global.sh"
echo "OK  $HOOKS_DIR/session-start-protocol-global.sh"

# 2a. Copy the Windsurf rules sync script (derives Windsurf rule files from
#     the canonical MDs hourly via cron, keeping the two enforcement systems
#     in sync). Optional — only relevant if you also use Windsurf/Cascade.
if [ -f "$SCRIPT_DIR/hooks/sync-windsurf-rules.sh" ]; then
  cp "$SCRIPT_DIR/hooks/sync-windsurf-rules.sh" "$HOOKS_DIR/sync-windsurf-rules.sh"
  chmod +x "$HOOKS_DIR/sync-windsurf-rules.sh"
  echo "OK  $HOOKS_DIR/sync-windsurf-rules.sh (run hourly via cron to sync Windsurf rules)"
fi

# 2b. Copy the test script
if [ -f "$SCRIPT_DIR/hooks/test-hooks.sh" ]; then
  cp "$SCRIPT_DIR/hooks/test-hooks.sh" "$HOOKS_DIR/test-hooks.sh"
  chmod +x "$HOOKS_DIR/test-hooks.sh"
  echo "OK  $HOOKS_DIR/test-hooks.sh (run: bash $HOOKS_DIR/test-hooks.sh)"
fi

# 3. Merge into settings.json — preserves everything already there (theme,
#    other hooks, etc). Idempotent: running twice does not duplicate the
#    entry.
if [ ! -f "$SETTINGS" ]; then
  echo '{}' > "$SETTINGS"
fi

HOOK_CMD="bash $HOOKS_DIR/session-start-protocol-global.sh"

TMP="$(mktemp)"
jq --arg cmd "$HOOK_CMD" '
  .hooks //= {} |
  .hooks.SessionStart //= [] |
  (
    if ([.hooks.SessionStart[].hooks[]?.command] | index($cmd)) then
      .
    else
      .hooks.SessionStart += [{
        hooks: [{
          type: "command",
          command: $cmd,
          timeout: 15,
          statusMessage: "Loading mandatory scientific method protocol..."
        }]
      }]
    end
  )
' "$SETTINGS" > "$TMP"
mv "$TMP" "$SETTINGS"
echo "OK  $SETTINGS (hook registered, rest of the file preserved)"

echo
echo "Done. Open Claude Code in ANY project on this machine to confirm — the"
echo "first system message should include 'MANDATORY READING injected"
echo "automatically by the global SessionStart hook'."
echo
echo "This guarantees the rules are DELIVERED to every session. It does not"
echo "guarantee they are FOLLOWED — see ../method/ENFORCEMENT_MODEL.md."
