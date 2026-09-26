# Codex implementation

Codex lifecycle hooks deliver the method and the project's bounded
`PROTOCOL-HEADER` into session context. The full project protocol remains the
source of history and evidence. The global hooks walk up from the session cwd,
so starting in a nested directory still finds the repository's
`EVIDENCE_PROTOCOL.md`.

## Install globally

```bash
./install.sh
```

The installer copies the canonical method documents to `~/.codex/evidence/`,
installs the scripts under `~/.codex/hooks/`, and merges three hooks into
`~/.codex/hooks.json` while preserving existing configuration:

- `SessionStart` injects the two method documents and the current protocol header.
- `UserPromptSubmit` refreshes and delivers the project header before each prompt.
- `PostToolUse` refreshes the header after tool activity, including protocol edits.

Run `codex` and use `/hooks` to review and trust the hooks. Codex requires
non-managed hooks to be reviewed and trusted before execution; a changed hook
definition requires review again. Project-local hooks are another option at
`<repo>/.codex/hooks.json`, but only load for trusted projects.

To confirm delivery, start or resume a Codex session in a project with
`EVIDENCE_PROTOCOL.md` and ask it to quote the current phase and a detail
from the method document. Also inspect `/hooks` for the registered sources.

## Delivery is not compliance

As with the Claude Code and Devin adapters, these hooks guarantee delivery
when Codex runs trusted hooks. They do not guarantee the method is followed.
Only project-specific code-level constraints can prevent an invalid outcome;
see [`../method/ENFORCEMENT_MODEL.md`](../method/ENFORCEMENT_MODEL.md).

Codex hook interface reference: [Hooks](https://developers.openai.com/codex/hooks).
