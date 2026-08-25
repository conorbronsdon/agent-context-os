---
name: Integration proposal
about: Propose an addition to the optional integration catalog
title: "Add <integration> to the integration catalog"
labels: enhancement
---

<!--
The catalog is deliberately small and opt-in. Nothing is installed or enabled at
setup. An entry is a discovery and risk document, so the bar is an honest
description of what a tool can reach — not popularity.

Read CONTRIBUTING.md ("Adding an integration to the catalog") before filling
this in. An entry that undersells a capability is worse than no entry.
-->

## Job it closes

<!--
What context does this get IN (notes, docs, transcripts, issues, highlights) or
what reviewed output does it get OUT? Name the loop it closes for someone
maintaining durable context in a git repo.

"It's popular" or "lots of people use it" is not a job. If the honest answer is
"it would be nice to have," say so — that is useful information.
-->

## Source

- Canonical documentation:
- Repository (if any):
- Hosted endpoint (if any):
- First-party, or community-maintained?
- Latest release and date, as of when you checked:

## Proposed catalog fields

- `id`:
- `kind`: <!-- mcp_server | skill_catalog | workspace_template | resource_catalog | agent_extension | connector | editor_guide | local_workspace -->
- `supported_agents`: <!-- claude_code | codex | cursor | gemini_cli | opencode | generic — list only what you verified -->
- `maturity`: <!-- verified if you checked the fields yourself; listed if you could not -->

## Capabilities

Describe the real surface, including the parts you would rather not advertise.

- [ ] `oauth`
- [ ] `sensitive_read` — what specifically can it read?
- [ ] `write`
- [ ] `remote_write`
- [ ] `publish`
- [ ] `overwrite`
- [ ] `delete`
- [ ] `destructive`
- [ ] `arbitrary_execution`

Notes on anything above, particularly anything that surprised you:

## Recommended default profile

<!--
The narrowest useful configuration. Which tools or scopes are on by default,
and what sits behind a separate confirmation group?

If the service has a genuine server-side read-only scope, say so — that is a
meaningful advantage and belongs in the entry.
-->

## What you could not verify

<!--
Required. "Nothing" is an acceptable answer, but an empty section is not.
Unverified per-client setup matrices, undocumented delete tools, and unclear
maintenance status all belong here rather than being quietly asserted.
-->
