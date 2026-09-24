---
name: Integration proposal
about: Propose an addition to the optional integration catalog
title: "Add <integration> to the integration catalog"
labels: enhancement
---

<!--
The catalog is deliberately small and opt-in. Nothing is installed or enabled at
setup. An entry is a discovery and risk document, so the bar is an honest
description of what a tool can reach - not popularity.

Read CONTRIBUTING.md ("Adding an integration to the catalog") before filling
this in. An entry that undersells a capability is worse than no entry.

IMPORTANT: This is a metadata-only catalog change.
- Do NOT install the integration.
- Do NOT authenticate to the integration.
- Do NOT call/use the integration.
No external account, credential, installation, or live integration call is required.
Please provide first-party documentation/evidence for all verified fields. Unverified fields must be explicitly disclosed.
-->

## Job it closes

<!--
What context does this get IN (notes, docs, transcripts, issues, highlights) or
what reviewed output does it get OUT? Name the loop it closes for someone
maintaining durable context in a git repo.

"It's popular" or "lots of people use it" is not a job. If the honest answer is
"it would be nice to have," say so - that is useful information.
-->

## Proposed catalog fields

- `id`:
- `name`:
- `summary`:
- `source_url`:
- `kind`: <!-- mcp_server | skill_catalog | workspace_template | resource_catalog | agent_extension | connector | editor_guide | local_workspace -->
- `supported_agents`: <!-- claude_code | codex | cursor | gemini_cli | opencode | generic - list only what you verified -->
- `maturity`: <!-- verified | listed | experimental -->
- `last_verified`: <!-- YYYY-MM-DD -->

## Installation

- `automatic`: false
- `scope`: <!-- none | project | user | project_or_user -->
- `prerequisites`:

## Data Boundary

Disclosure must be complete.
- `credentials`:
- `reads`:
- `writes`:

## Capabilities

Describe the complete reachable surface, even if recommended use is read-only.
The catalog must describe the full surface; it does not disable tools or enforce allowlists or default profiles.

- [ ] `read`
- [ ] `sensitive_read`
- [ ] `write`
- [ ] `remote_write`
- [ ] `publish`
- [ ] `overwrite`
- [ ] `delete`
- [ ] `destructive`
- [ ] `arbitrary_execution`
- [ ] `oauth`

- `details`:
  <!--
  Required non-empty list. Describe the tool's full reachable surface area,
  not merely the preferred/recommended subset. Include relevant read, write,
  delete, overwrite, remote-write, or arbitrary-execution surface details
  when applicable. Also contain any recommended client-side restrictions
  or scope/tool recommendations. Stay consistent with the typed capability flags.
  -->

## Confirmation

- `required_for`: <!-- credential_setup, external_install, read_sensitive, write, write_remote, publish, overwrite, delete, arbitrary_execution, oauth, destructive -->
- `notes`: <!-- Recommended confirmation guidance belongs here -->

## Risk Tags

- `risk_tags`: <!-- e.g., sensitive-read, remote-write, publish-capable, overwrite-capable, delete-capable, arbitrary-execution, oauth, destructive-capable -->

## Evidence & Health

- `evidence`: <!-- Non-empty list of first-party links supporting the fields you verified. Listed or experimental entries still require evidence for the claims they make. -->
- `health_check`:

## Uninstall

- `instructions`:
- `removes_user_data`: <!-- true | false -->

## Optional host evidence

<!--
Fill this in only if you have tested this integration on a named host. An
OpenClaw claim needs a real OpenClaw integration test; generic MCP support is
not host evidence. This is proposal evidence, not a catalog field yet. Do not
include credentials, private data, or account identifiers. See
docs/integrations-guide.md#host-compatibility-evidence.
-->

- Integration and host:
- Tested host surface and exact version:
- Test date (YYYY-MM-DD):
- Credential model and storage location (no secret values):
- Network egress destinations:
- Reachable side effects, identifying writes and destructive actions:
- Confirmation gates observed on this host:
- Health-check command and observed output shape (redacted):
- Verified uninstall and credential revocation steps:
- Evidence location (test log, reproducible steps, or reviewable artifact):

## What you could not verify

<!--
Required for listed or experimental entries. "Nothing" is an acceptable answer, but an empty section is not.
Unverified per-client setup matrices, undocumented delete tools, and unclear
maintenance status all belong here rather than being quietly asserted.
-->
