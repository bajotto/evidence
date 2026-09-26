# Cross-agent memory, search, multi-user, and multi-machine

This method was compared against a memory tool built for a different problem
(persisting cross-agent memory across machines and teams). Four of its
capabilities are relevant here. Three of them this method already has, for
free, from decisions already made elsewhere in this repo — they just weren't
written down as capabilities. The fourth is a real, scoped gap this document
also closes.

## 1. Search instead of injecting the whole body — closed by `protocol-search.sh`

The `PROTOCOL-HEADER` is capped at 8KB (`protocol-header.sh`, `MAX_BYTES`),
but the body it summarizes is not — one real project's `SCIENTIFIC_PROTOCOL.md`
reached ~722KB. Before this script existed, an agent that needed anything
past the header had only one option: read the entire body. That is slow,
burns context, and doesn't scale with protocol age.

[`protocol-search.sh`](protocol-search.sh) queries the body directly instead:

```bash
protocol-search.sh hypotheses SCIENTIFIC_PROTOCOL.md          # every H<n>, with its Status
protocol-search.sh incidents  SCIENTIFIC_PROTOCOL.md [PATTERN] # incident log, optionally filtered
protocol-search.sh phase      SCIENTIFIC_PROTOCOL.md 2        # just that Phase section
protocol-search.sh grep       SCIENTIFIC_PROTOCOL.md PATTERN  # free text, with enclosing section
```

The generated header now advertises these four commands under "Full-text
search," so an agent that only has the header in context (the normal case)
still knows the tool exists without having read this file.

This does not replace reading the full body before a scale decision — see
`SCIENTIFIC_METHOD.md`'s gates. It replaces reading the full body to answer
"what happened in Phase 2" or "has this failure mode occurred before."

## 2. Cross-agent memory sharing — already true, by construction

The design already separates the memory itself from any one tool's delivery
mechanism:

- The memory is `SCIENTIFIC_PROTOCOL.md` — plain markdown, in the project's
  own repo, in no tool-specific format. Any agent that can read a file reads
  the same memory.
- `method/` is the tool-agnostic core. `claude/`, `devin/`, and (via
  `claude/hooks/sync-windsurf-rules.sh`) Windsurf/Cascade are three
  independent delivery mechanisms that all inject the same protocol into
  three different agents' context, with no shared runtime between them.

That is the cross-agent property directly: switch from Claude Code to Devin
on the same project, and the next session's hook reads the same
`SCIENTIFIC_PROTOCOL.md` — nothing project-specific needs to change, and
nothing is lost, because nothing tool-specific was ever written into the
memory in the first place.

Adding a fourth agent (Cursor, Codex, Copilot, ...) means writing a fourth
delivery adapter — a session-start hook that finds and injects the header,
following the pattern in `claude/hooks/session-start-protocol-global.sh` or
the static-regeneration pattern in `claude/hooks/sync-windsurf-rules.sh` for
tools without a hook API. It does not mean touching the memory format itself.

## 3. Multi-user support with attribution and audit — use git, don't rebuild it

The template already asks for attribution in the two places it matters:

```
**Approval to scale:** [awaiting / granted, by whom, when]
### Incident: [date]
```

The audit trail underneath that does not need a parallel system: this file
lives in a git repository. `git log -p -- SCIENTIFIC_PROTOCOL.md` is the
complete, tamper-evident history of every phase transition, approval, and
incident entry — who wrote it, when, and what the file looked like before
and after. `git blame SCIENTIFIC_PROTOCOL.md` attributes any specific line.
Building a second attribution/audit database alongside git would track the
same facts git already tracks correctly, and would be one more thing that
can drift from the truth.

If a team wants this surfaced without typing the git commands: a thin
wrapper (`git log --follow --format='%ad %an %s' -- SCIENTIFIC_PROTOCOL.md`)
is a few lines, not a new subsystem, and is intentionally left to each
project rather than templated here — same reasoning as Layer 3 in
`ENFORCEMENT_MODEL.md`.

## 4. Multi-machine sync — also git, with one sharp edge

`SCIENTIFIC_PROTOCOL.md` syncs across machines exactly the way the rest of
the project does: `git push` / `git pull` / `git clone`. No separate server,
no separate sync protocol — the project's existing git remote already is
that layer.

The one real edge case: the `PROTOCOL-HEADER` block is derived, machine-
generated text. If two machines each run a session against the same branch
before pulling the other's changes, a normal git merge can conflict *inside*
that block. Resolve it like any derived artifact, not like hand-written
prose:

1. Resolve the **body** conflicts first (the actual hypotheses, phases,
   incidents) — that's the content a merge tool should help with.
2. For the header block itself, discard both conflicting versions rather
   than hand-merging them.
3. Run `protocol-header.sh sync SCIENTIFIC_PROTOCOL.md` to regenerate the
   header from the now-merged body.
4. Run `protocol-header.sh check SCIENTIFIC_PROTOCOL.md` to confirm it's
   valid, then commit.

Never hand-edit the text between `<!-- PROTOCOL-HEADER:START -->` and
`<!-- PROTOCOL-HEADER:END -->` directly for the same reason you wouldn't
hand-edit a generated lockfile conflict — regenerate it from the source of
truth (the body) instead.
