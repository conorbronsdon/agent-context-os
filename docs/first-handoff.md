# Your first reviewed handoff

Try one small decision in Claude Code, then pick it up in Codex. The goal is to
finish a useful handoff in about ten minutes **after prerequisites are installed**.
This is a target to test, not a measured onboarding guarantee. You need Git,
Bash, Python 3.10+, and access to both agents. Use a disposable clone containing
only this synthetic example; no personal imports or external integrations are
needed. See [getting started](getting-started.md) if a prerequisite is missing.

The source template's `CLAUDE.md` imports `@AGENTS.md`, so Claude receives the
shared lifecycle instructions as well as its host adapter. In older releases
or personalized copies, check for that import. Current Claude Code defaults to
loading `AGENTS.md` only when no `CLAUDE.md`, `.claude/CLAUDE.md`, or
`CLAUDE.local.md` is on the project path. Keeping both root files without an
import can therefore omit the shared instructions. An alternative is the
user-selected Project instructions value `claude-md-and-agents-md`; do not
change global configuration automatically. Run `/memory` or `/context` to
inspect loading. See [Anthropic's memory documentation](https://code.claude.com/docs/en/memory#agentsmd)
(checked 2026-10-04). This source fix does not rewrite published release assets.

## 1. Set up one shared workspace

Start with the five attached assets from
[v1.1.1](https://github.com/conorbronsdon/agent-context-os/releases/tag/v1.1.1).
Until that release is published, use
[v1.0.0](https://github.com/conorbronsdon/agent-context-os/releases/tag/v1.0.0)
and replace `v1.1.1` with `v1.0.0` in the commands below, or use the source
alternative. Follow the release's `OFFLINE-VERIFY.md` before extracting or
running setup. Use a fresh directory for this exercise. The attached template
tar is the workspace; GitHub's generated source archives are different
artifacts.

After verification and extraction, initialize an independent Git repository so
the exercise cannot inherit an enclosing repository's hooks or Git evidence:

```bash
cd agent-context-os-template-v1.1.1
git init
bash scripts/setup.sh --agents claude,codex
```

For testing unreleased source instead, clone the development repository into a
new `handoff-demo` directory and run setup there:

```bash
git clone https://github.com/conorbronsdon/agent-context-os.git handoff-demo
cd handoff-demo
bash scripts/setup.sh --agents claude,codex
```

Record which
source and version you tested; source-branch support may differ from the release.

Version 1.0.0 includes the CRLF setup-input fix and end-skill date-line
clarification from the synthetic handoff observations.

Review the agent-selection diff before approving it. Decline optional commits,
remote changes, and hooks for this exercise. Launch `claude` from this directory,
invoke `/setup`, and answer the interview with this fictional project:

> Lantern is a small export tool. Its next task is CSV export for spreadsheet
> analysis. We considered PDF export and rejected it because users need to sort
> the data. The launch date is unconfirmed. Keep the example within this clone.

Review the proposed context files and approve that exact proposal only if it
matches these facts. Confirm that the proposal initializes `state/current.md`
as well as the project context; a receipt alone does not establish start
readiness. The agent should report the resulting receipt. Run
`bash scripts/contextos.sh start` and check that its JSON reports
`"initialized": true` before proceeding. The Markdown briefing is a source
preview and does not display this readiness field.

## 2. Save one decision with Claude

Invoke `/end` and provide this handoff:

> Record the decision to implement CSV export, including why PDF was rejected.
> Next session should outline CSV columns. The launch date remains unconfirmed.
> Use decision ID `lantern-export-001`. In the rationale, record
> `Review status: accepted after exact-proposal review; Reviewed by: Demo reviewer
> (self-reported); Supersedes: none`. This is a fictional reviewer for the exercise.

Inspect the proposed decision row and session note. Approve the exact proposal
after review. Save the receipt path the agent reports. Do not commit or push as
part of this exercise; the second agent reads the same local files.

These labels are a Markdown convention: put the ID in the existing `decision`
string and review/supersession details in its `rationale` string. They are not
new kernel payload fields. Until approval and successful apply, the row is a
proposal for acceptance; merely storing a proposal does not make it accepted.
Use a reviewer name only when the reviewer supplied or confirmed it. Existing
rows without review metadata remain unknown rather than retrospectively
accepted. Neither the labels nor the receipt authenticate the reviewer.

If the diff invents a launch date or omits the reason for rejecting PDF, decline
it. Ask the agent to generate a corrected proposal, inspect its new diff and
digest, and approve only that proposal. An unapplied proposal remains stored
for inspection but does not change durable context or create an apply receipt.

For an independent view in a terminal:

```bash
bash scripts/contextos.sh history --details --path state/decisions.md
```

You should see the self-reported runtime, changed path, and the recorded diff
when its matching proposal is still available. Receipts do not authenticate the
human reviewer. Missing details are reported explicitly.

## 3. Resume with Codex

Close Claude, launch `codex` from the same directory, and invoke `$start`.
Then ask, without restating the answers:

> What export should we implement, why was the alternative rejected, and can
> we promise a launch date? Cite the files you used. Suggest the next small step.

A successful handoff identifies CSV, explains spreadsheet analysis and the
rejected PDF option, keeps the launch date unresolved, and cites the actual
decision/session files. It proposes outlining columns without silently making
new durable decisions. A confident answer with no supporting source fails this
exercise.

Ask which decision ID it used and who is recorded as reviewer. The expected
answer points to `lantern-export-001` and the self-reported Demo reviewer,
while preserving the limit that this is not independently verified identity.

## Optional: replace a decision and preserve its review trail

Return to the saving agent and request a new end proposal:

> The fictional reviewer now wants JSON export for API ingestion. Record
> decision ID `lantern-export-002`, rationale `API ingestion; Review status:
> accepted after exact-proposal review; Reviewed by: Demo reviewer
> (self-reported); Supersedes: lantern-export-001`, and rejected alternative
> `CSV spreadsheet export`. Preserve the original decision row. Update the
> current handoff to point to the replacement. The launch date stays unconfirmed.

Inspect the full diff and approve only if those links and facts are present.
An append-only decision log preserves the old row, so the new row must name
what it replaces; a newer timestamp alone does not explain supersession.
Resume in a fresh receiving session and ask for the current format, ID,
reviewer, superseded ID and supporting source. It should cite JSON and
`lantern-export-002`, explain its link to `lantern-export-001`, and keep the
date unresolved. Finding CSV in history is expected; treating it as current
fails the replacement check.

This convention leaves enforcement of record IDs and supersession links to
review. Git records committed authorship and changes; it does not, by itself,
establish decision-level acceptance or authenticate the human reviewer.

## 4. Inspect and compare

```bash
bash scripts/contextos.sh start --format markdown
```

The preview labels sources and their recorded freshness. It does not prove what
Codex read. Compare Codex's citations with the source files and the saved diff.

Record elapsed setup/handoff time, repeated explanations, missed constraints,
and whether you could explain what was saved. If the answer is wrong, inspect
the source and proposal first: was the fact saved, replaced, omitted, or simply
not used? Run `bash scripts/contextos.sh doctor` for setup problems.

To test what happens when a decision changes, see
[how to spot stale context and test your next session](https://chainofthought.show/context-engineering/?utm_source=github&utm_medium=referral&utm_campaign=repo-first-handoff&utm_content=agent-context-os)
on Chain of Thought. The resource includes a separate, downloadable exercise
with repaired and conflicting handoffs, plus the conversations behind the practice.

For controlled comparisons with a plain handoff note, use the
[continuity benchmark](continuity-benchmark.md). For your own project, continue
with [getting started](getting-started.md); select additional agents and imports
when needed. Other hosts retain their own documented command names.

The [synthetic handoff observations](https://github.com/conorbronsdon/agent-context-os/blob/c4648d80fc72ed27abce527a05e952e42580783b/docs/evidence/synthetic-handoffs-2026-09-29/report.md)
record kernel trials and fresh receiving-agent checks that informed this guide.
They do not establish human onboarding time or native host behavior.
