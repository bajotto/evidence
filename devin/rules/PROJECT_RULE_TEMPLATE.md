---
trigger: always_on
---

<!--
  Template for a per-project Devin rule.

  Save this file as <your-project>/.windsurf/rules/<name>.md — Devin's CLI
  reads project rules from that directory (confirmed via `devin rules
  paths`).

  THE FRONTMATTER ABOVE IS NOT OPTIONAL. Without it, Devin silently treats
  the file as `manual` activation — it exists, `devin rules list` shows
  it, but it is NOT injected into context automatically. This was found by
  testing, not by reading documentation: a first version of this template
  without frontmatter showed up as "[Windsurf] manual" instead of
  "always-on", and only the frontmatter fixed it. If you change the
  `trigger` value, the options are `always_on`, `manual`, `glob` (needs a
  `globs:` field), and `model_decision` (needs a `description:` field) —
  see Windsurf's rules documentation for the other modes.

  Delete this comment block once you've filled in the sections below.
-->

# [PROJECT_NAME]

## Critical rules

The rules below caused, or nearly caused, a real incident in this project.
Full detail: `EVIDENCE_PROTOCOL.md`.

1. **[Your highest-cost failure mode].** [What to do instead, and why.]
2. **[Second rule, if you have one].** [Same structure.]
3. **Before claiming "X is confirmed" or "X is in production," verify the
   real system state** — a git push, a passing test, or a code comment is
   not confirmation.

## What this project does

[Short description.]

## Build / test / run

[Exact commands.]

## Method

This project follows Evidence, described in `method/EVIDENCE.md`,
and the enforcement model in `method/ENFORCEMENT_MODEL.md` (adjust the path
to wherever you vendor this repo's `method/` folder, or rely on the global
hook from `../install.sh` if it's installed on this machine). The running
protocol for this project is in `EVIDENCE_PROTOCOL.md`, based on
`method/PROJECT_PROTOCOL_TEMPLATE.md`.
