# Try the three-file starter

Use this for one project when you want the next agent session to pick up where
you stopped. You need a file-capable agent and a text editor. Git is useful for
reviewing changes and retaining earlier handoffs, but the starter runs no code.

## Put the files beside your work

Copy only these files from `starter/` into a new project or a project that does
not already have a context system:

- [AGENTS.md](../starter/AGENTS.md): instructions for reading and maintaining context.
- [current-work.md](../starter/current-work.md): the current objective and constraints.
- [handoff.md](../starter/handoff.md): the latest session's result and resume point.

Replace the bracketed placeholders with your own context. Start with one active
objective. Leave the first handoff empty of claims until a session has occurred.
Keep sensitive context in an appropriately private location.

If the project already has `AGENTS.md`, merge the useful instructions into it;
do not replace its existing rules. Check for existing files with the other two
names before copying. Existing full-template Context OS users should try this
in a separate project: its direct file updates are a separate workflow from
the full template's proposal/apply lifecycle. Adding these files beside `state/`
and `sessions/` would create competing sources of truth.

## Start a session

Explicitly ask the agent to read the files. This works around differences in
which instruction filenames agents discover automatically:

> Read AGENTS.md, current-work.md, and handoff.md. Check the relevant project
> files, summarize where we are, and propose the next action. Flag anything
> contradictory or unverified before relying on it.

Then work normally. You do not need to install a skill or remember a slash command.

## Finish or checkpoint

> Update current-work.md and replace handoff.md with this session's changes,
> actual verification results, unfinished work, and where to resume. Preserve
> unresolved items and show me the diff. Do not commit or publish.

Review the result. Correct unsupported claims and remove completed work from
the active view. Check that any date comes from the current session, not a
guess or an earlier handoff. If no reliable date is available, keep it `unknown`.
Commit when you want to retain the checkpoint in Git history.

If a needed decision disappears, check its linked source or a relevant Git
revision. Otherwise ask the user; current code alone does not establish what
the user approved.

Current work answers "What are we trying to do now?" The handoff answers
"What happened in the last session that the next session needs to know?"
If a handoff only repeats the next action, keep it short. It does not need to
be a second project plan.

## Example: finish in Claude, resume in Codex

This is an illustrative workflow, not a recorded agent run or a benchmark.

Suppose Claude changes a CSV importer to accept quoted commas. At the end,
you review a handoff that identifies the changed parser, records the check
that actually passed, and notes that embedded newlines still need testing.
The current-work file retains the objective: support the agreed CSV inputs
without changing the output schema.

In a fresh Codex session in that same project, use the start prompt above.
A successful resumption identifies the newline case, inspects the parser and
existing tests, and proposes the missing check without asking you to explain
the project again. Verify that behavior yourself; the files cannot guarantee
an agent will read or follow them.

## Evidence so far

A [supplied-snapshot simulation](minimal-starter-evidence.md) tested saved
decisions, a stale handoff, and a deliberately removed decision. It also found
an unsupported date in a generated checkpoint. The linked record includes the
inputs, outputs, limitations, and the resulting date-rule change. It does not
replace a trial on your own project.

## Evaluate it for one week

Use one active project. Keep a short trial note outside the starter files so
measurement does not become more agent context. After each session, record:

| Observation | What to record |
|---|---|
| Repeated explanation | What you had to explain again despite the saved context |
| Missed decision | A decision the agent overlooked or contradicted |
| Incorrect resumption | A stale or wrong next action and how you corrected it |
| Maintenance | Minutes spent reviewing and correcting the two state files |
| Missing capability | What you needed from your previous system and why |

Include at least one fresh session and, if you use both, a switch between
Claude Code and Codex. Compare against your normal workflow. Keep the starter
if continuity improves enough to justify the maintenance. If it does not,
identify the failure before adding more structure. No week-long human usage
results are available yet.

## Add structure when a problem repeats

| Recurring problem | Smallest next addition |
|---|---|
| Too much context to read every session | A routing index pointing to topic files |
| A useful procedure must be explained repeatedly | A [portable skill](first-skill.md) |
| Decisions no longer fit beside current work | A decision log, linked from current work |
| Concurrent sessions overwrite each other's state | Separate worktrees and an explicit reconciliation process; evaluate the full template's write controls |
| You need managed lifecycle updates or host adapters | Review the [full-template setup](getting-started.md#before-you-clone) and its costs |

Moving to the full template is a reviewed migration: map current work into
`state/`, the latest handoff into `sessions/`, and reconcile the instruction
files. Use its [migration guide](migration-guide.md). The starter has no
automatic upgrade command; retire superseded active files only after checking
that useful context was preserved.
