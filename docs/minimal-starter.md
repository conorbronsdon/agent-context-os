# Try the experimental three-file starter

This is an optional experiment, not an established default. Use it for one
project when you want the next agent session to pick up where
you stopped. You need a file-capable agent and a text editor. Git is useful for
reviewing changes and retaining earlier handoffs, but the starter runs no code.

## Consider one file first

For a small sequential project, keep the working instructions, current objective,
constraints, and latest handoff in one `AGENTS.md`. Use clearly labeled sections
and retain only the latest useful checkpoint. Ask the agent to read that file
at the start and show its proposed update at the end. Preserve existing project
rules and use the date and verification rules in the templates below.

Use the three-file layout when separate current-work and session notes help
you review changes. Neither layout guarantees retention, and the available
evidence does not establish that three files outperform one.

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

Use up to six ordinary sessions on one active project over a week. Stop when
the work finishes; do not manufacture sessions. Compare one `AGENTS.md` (A)
with the three-file layout (B), using the sequence A, B, B, A, A, B. Keep the
same agent/model and one active layout at a time. Preserve the facts when
switching layouts and record conversion time separately. Start fresh sessions
and include an ordinary overnight break if the work spans multiple days.

Keep a short trial note outside the active context files. After each session,
record what you had to explain again, saved decisions that were missed or
contradicted, and any wrong next action. Record actual human minutes spent
reviewing the work and maintaining its checkpoint. Distinguish an unresolved
decision that needs your answer from an answer the agent overlooked.

Choose one file on a practical tie. Keep three only if the separate handoff
prevents enough mistakes or repeated explanations to justify its upkeep. Task
order and learning can affect the comparison, so record concrete examples
before attributing a difference to file layout. No week-long human usage or
maintenance-time results are available yet.

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
