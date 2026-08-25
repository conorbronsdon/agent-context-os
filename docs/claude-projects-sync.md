# Using repo files in Claude.ai Projects

Claude Code reads this repository from the filesystem. Claude.ai Projects can use selected files only after you upload them as project knowledge. This is a manual copy with no live sync, write-back, git integration, slash-command activation, tool pre-approval, or lifecycle equivalence.

Treat the repository as the maintained source. Record which file version was uploaded, and manually replace it when the source changes.

## Choose a minimal knowledge set

Think of this repo as the source. claude.ai projects are manual consumers. You upload selected files into project knowledge, but browser projects do not provide repository writes, checked-in hooks, or slash-command behavior.

| Project purpose | Possible files |
|---|---|
| General personal context | A deliberately sanitized `identity/who-i-am.md` |
| Writing | `writing/skills/avoid-ai-writing/SKILL.md` as guidance |
| One recurring project | `projects/<project>/context.md` and `strategy.md` |
| A repeated workflow | The relevant `.agents/skills/<name>/SKILL.md` as instruction text |

Do not upload repository-wide state by default. Avoid credentials, private links, unrelated client context, raw session logs, and files the Project's collaborators should not read.

`CLAUDE.md` and `ROUTING.md` contain Claude Code-specific command and routing information. Upload them only if the relevant parts are useful as background; do not tell users they become active configuration in Claude.ai.

## Upload and use

In Claude.ai:

1. Open the intended Project.
2. Review the Project's collaborators and data boundary.
3. Open Project knowledge and upload the selected files.
4. Ask Claude to use an uploaded workflow as guidance by name.

An uploaded `SKILL.md` is plain project knowledge. Asking “apply the standup workflow” may help Claude follow its procedure, but frontmatter invocation policy, `allowed-tools`, Codex metadata, and Claude Code slash commands do not activate in Claude.ai.

## Keep copies current

When a source file changes:

1. review the repository diff;
2. identify every Claude.ai Project that has a copy;
3. remove or replace the old upload manually;
4. verify the displayed file and its date; and
5. note any Project that intentionally remains on an older version.

There is no automatic propagation. If you cannot confirm a Project's uploaded version, treat it as stale.

## Bring changes back

Claude.ai cannot write this repository. If it drafts an improvement:

1. Copy the draft into a temporary file outside the repository.
2. Compare it with the maintained source and remove Project-only or sensitive
   context.
3. Propose the exact destination and diff before changing repository files.
4. Apply only the reviewed change, then run
   `bash scripts/validate-all.sh --workspace`.
5. Review the git diff and approve any commit or push separately.

Claude can follow provider-neutral instructions in an uploaded skill file, but
host-specific tool grants, hooks, paths, and frontmatter do not carry over
automatically. Use this only when the browser Project has the required context
and tools; upload the `SKILL.md`, then reference it by name in the conversation.

## When not to use a Project copy

Use Claude Code or Codex against the repository when the job requires current state, repository writes, lifecycle commands, validation, git review, or enforced confirmation boundaries. Use Claude.ai Project knowledge for a focused, manually managed reference set.
