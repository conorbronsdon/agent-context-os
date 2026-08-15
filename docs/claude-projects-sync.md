# Using repo files in Claude.ai Projects

Claude Code reads this repository from the filesystem. Claude.ai Projects can use selected files only after you upload them as project knowledge. This is a manual copy with no live sync, write-back, git integration, slash-command activation, tool pre-approval, or lifecycle equivalence.

Treat the repository as the maintained source. Record which file version was uploaded, and manually replace it when the source changes.

## Choose a minimal knowledge set

Upload only the files needed for the Project's purpose. Every upload exposes that content to the selected Claude.ai Project and its configured collaborators.

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

1. copy the proposed text into an ignored local staging file;
2. compare it with the current canonical repository file;
3. resolve conflicts and remove sensitive residue;
4. apply only the reviewed parts; and
5. run `bash scripts/validate-all.sh` before commit.

Do not ask a browser Project to output every private conversation or knowledge file merely to create a backup. Use the metadata-first [migration guide](migration-guide.md) when bringing existing Project context into the repository.

## When not to use a Project copy

Use Claude Code or Codex against the repository when the job requires current state, repository writes, lifecycle commands, validation, git review, or enforced confirmation boundaries. Use Claude.ai Project knowledge for a focused, manually managed reference set.
