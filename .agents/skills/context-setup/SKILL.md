---
name: context-setup
description: Build, import, or refresh this workspace's identity, project, reusable-workflow, and weekly-state files through a guided review. Use only when the user explicitly asks to initialize or redo workspace context.
---

# Set up workspace context

Build useful context without silently overwriting user data.

## Guardrails

- Ask questions one at a time and inspect existing files before proposing changes.
- Preserve the user's wording; do not embellish credentials, goals, or biography.
- Require approval before replacing populated files, broad writes, commits, or pushes.
- Never request or store credentials or ingest a raw account export into tracked context.

## Procedure

### 1. Confirm storage and audience

Explain that tracked identity, project, state, session, and imported context is
visible to repository collaborators and configured agents. Deleting it later
does not erase git history. Recommend local-only or private storage by default;
a public remote requires deliberately sanitized content. Stop before collecting
personal information unless the user explicitly confirms the audience.

### 2. Choose and inspect the starting point

Ask whether to start from answers, selected existing material, or both. For
existing material, follow `docs/migration-guide.md` and accept only a reviewed,
narrow packet. Read the existing identity, project index, current state, weekly
priorities, and routing files. Classify each as missing, placeholder, or populated.

### 3. Gather reviewed context

One question at a time, gather identity, current focus, relevant background,
three-month goals, working preferences, optional useful personal context,
verifiable proof points, and approved public links. Then gather one recurring
project: purpose, audience, current focus, non-goals, prior decisions, and
repeated workflows. Finally gather weekly outcomes, non-goals, success criteria,
and blockers. Draft the smallest coherent file map and routing additions.

Portable repeated workflows belong under `.agents/skills/`; facts stay in their
identity, project, or state source and are referenced rather than copied.

### 4. Propose and apply deterministically

Encode the reviewed file map as JSON under `.context-os/inputs/`, with `files`
mapping repository-relative paths to complete desired content. Add a path to
`replace_populated` only after explicit approval to replace that populated file.
Use `{{TODAY}}` where the deterministic local date belongs.

Run `bash scripts/contextos.sh propose setup --input <payload.json>`. Present every
returned diff and its proposal digest. The digest binds the exact content but
does not authenticate a human approver; rely on the host permission boundary.
After explicit approval of that exact proposal, run:

```text
bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
```

The kernel must refuse path escapes, writes outside context paths, unapproved
populated replacements, changed targets, or concurrent applies.

Run `bash scripts/validate-all.sh --workspace`, report the receipt and result, and offer a
commit only after final diff review. Suggest `$start` next and `$end` to close.
