---
name: context-setup
description: Build, import, or refresh this workspace's identity, project, reusable-workflow, and weekly-state files through a guided review. Use only when the user explicitly asks to initialize or redo workspace context.
---

# Set up workspace context

## Execution roots (required)

Use the exact roots supplied by the host attachment: `KernelRoot` is the trusted
Context OS product containing `scripts/contextos.sh`; `ContextRoot` owns tracked
identity and lifecycle state; and `WorkingRoot` is the ordinary application.
For an external attachment, require all three exact absolute paths and run:

```text
bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> <command>
```

Do not search upward or infer a root from cwd or the skill installation. The
kernel must validate the ignored local binding before strict lifecycle work. A
missing, moved, stale, linked, nested, or mismatched binding stops the workflow;
use the explicit `project rebind` proposal after a legitimate move. ContextRoot
owns all lifecycle writes. WorkingRoot is read-only evidence. The colocated
`bash scripts/contextos.sh <command>` compatibility form remains valid.

Throughout this procedure, resolve every context path beneath `ContextRoot`. In
split mode, spell local paths as absolute `<ContextRoot>/...` paths and invoke
every lifecycle command through the absolute KernelRoot wrapper with both exact
role options. In colocated mode, run the relative compatibility commands from
the colocated root, where ContextRoot and WorkingRoot are the same directory.

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
existing material, follow `<KernelRoot>/docs/migration-guide.md` and accept only
a reviewed, narrow packet. Read the existing identity, project index, current
state, weekly priorities, and routing files beneath ContextRoot. Classify each
as missing, placeholder, or populated. Do not read similarly named files from
WorkingRoot as shared context.

### 3. Gather reviewed context

One question at a time, gather identity, current focus, relevant background,
three-month goals, working preferences, optional useful personal context,
verifiable proof points, and approved public links. Then gather one recurring
project: purpose, audience, current focus, non-goals, prior decisions, and
repeated workflows. Finally gather weekly outcomes, non-goals, success criteria,
and blockers. Draft the smallest coherent file map and routing additions.

Portable repeated workflows belong under `<ContextRoot>/.agents/skills/`; facts
stay in their ContextRoot identity, project, or state source and are referenced
rather than copied.

### 4. Propose and apply deterministically

Encode the reviewed file map as JSON under
`<ContextRoot>/.context-os/inputs/`, with `files` mapping ContextRoot-relative
paths to complete desired content. Add a path to `replace_populated` only after
explicit approval to replace that populated file. Use `{{TODAY}}` where the
deterministic local date belongs.

Run exactly one of these forms:

```text
split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> propose setup --input <ContextRoot>/.context-os/inputs/<payload.json>
colocated: bash scripts/contextos.sh propose setup --input .context-os/inputs/<payload.json>
```

Present every returned diff and its proposal digest. The digest binds the exact
content but does not authenticate a human approver; rely on the host permission
boundary. After explicit approval of that exact proposal, run the matching form:

```text
split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> apply <ContextRoot>/<proposal> --confirm <digest> --runtime <active-runtime>
colocated: bash scripts/contextos.sh apply <proposal> --confirm <digest> --runtime <active-runtime>
```

The kernel must refuse path escapes, writes outside context paths, unapproved
populated replacements, changed targets, or concurrent applies.

Validate with the matching mode:

```text
split:     bash <KernelRoot>/scripts/contextos.sh --context-root <ContextRoot> --working-root <WorkingRoot> doctor
colocated: bash scripts/validate-all.sh --workspace
```

Do not run a ContextRoot-relative product validator from WorkingRoot. Report the
receipt and result, and offer a ContextRoot commit only after final diff review.
Suggest `$start` next and `$end` to close.
