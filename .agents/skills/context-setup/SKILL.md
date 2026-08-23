---
name: context-setup
description: Build, import, or refresh this workspace's identity, project, reusable-workflow, and weekly-state files through a guided review. Use only when the user explicitly asks to initialize or redo workspace context.
---

# Set up workspace context

Build useful context from the user's own words or selected migration material without silently overwriting existing files.

## Guardrails

- Ask questions one at a time.
- Inspect existing files before proposing changes. Treat non-placeholder content as user data.
- Preserve the user's wording; do not embellish credentials, goals, or biography.
- Show the proposed file map and summarize replacements before writing.
- Require approval before overwriting populated files, creating broad batches of files, committing, or pushing.
- Never request or store passwords, access tokens, recovery codes, or other credentials.
- Never ingest a raw account export or complete conversation archive into tracked context.

## Procedure

### 1. Confirm storage and audience before collecting context

Explain that identity, project, state, session, and imported context can be
sensitive. Tracked files are visible to every repository collaborator and
configured agent, and deleting them later does not erase them from git history.
Recommend a local-only workspace or private remote by default; a public remote
requires deliberately sanitized content. Keep raw exports and migration staging
outside tracked files.

Ask the user to confirm that the current storage location, repository audience,
and intended agent access are appropriate. If they do not explicitly confirm,
stop before reading migration material or asking for personal information.

### 2. Choose the starting point

Ask whether the user wants to start from their answers, selected existing material, or both.

For existing material, read `docs/migration-guide.md`. Ask for one reviewed migration packet or a narrow set of source files. Inventory the selected input, mark claims that need verification, identify sensitive items that should stay out of the workspace, and propose destinations. Do not read beyond the scope the user selected.

### 3. Inspect the workspace

Read:

- `identity/who-i-am.md`
- `identity/professional-background.md`
- `projects/README.md`
- `state/current.md`
- `state/weekly-priorities.md`
- `ROUTING.md`

Classify each as missing, placeholder-only, or populated. Tell the user what can be filled safely, what would be merged, and what would be updated.

### 4. Gather identity context

Ask for, one question at a time:

1. name and a one-sentence description,
2. current role or main focus,
3. relevant background,
4. three-month goals,
5. working preferences,
6. optional personal context that genuinely helps,
7. a short self-description,
8. verifiable credentials or proof points, and
9. public links they want recorded.

Use approved migration items as candidate answers, then ask only for missing details or verification. Draft updates to the two identity files, preserve the user's language, and use today's date for `**Last Updated:**`.

### 5. Gather the first project

Ask for one recurring project, then gather:

1. purpose and desired outcome,
2. audience or collaborators,
3. current focus and explicit non-goals,
4. decisions already made,
5. repeated tasks, and
6. the one or two repeated tasks most worth standardizing.

Draft `projects/<project-slug>/context.md` and `projects/<project-slug>/strategy.md`. For each approved repeated workflow, draft a portable skill at `.agents/skills/<project-slug>-<workflow-slug>/SKILL.md`; keep project facts in the project files and reference them from the skill rather than copying them. Add a concise route to `ROUTING.md`.

Offer to repeat this phase for another project.

### 6. Gather weekly state

Ask for:

1. the top three outcomes for this week,
2. explicit non-goals,
3. what a good week looks like, and
4. blockers or items waiting on someone else.

Draft `state/current.md` and `state/weekly-priorities.md` with current dates.

### 7. Review and apply

Present:

- every file to create or edit,
- populated content that would be replaced,
- imported claims that remain unverified,
- selected source material that will stay outside tracked files,
- the proposed routing additions, and
- any reusable workflow skills.

Wait for approval, then apply only the approved changes. Run `bash scripts/validate-all.sh` and report the result. Offer a commit only after the user reviews the diff.

Finish by suggesting `$start` for the next working session and `$end` when that session is complete.
