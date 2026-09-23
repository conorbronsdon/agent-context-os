# Your first reviewed handoff

Try one small decision in Claude Code, then pick it up in Codex. The goal is to
finish a useful handoff in about ten minutes **after prerequisites are installed**.
This is a target to test, not a measured onboarding guarantee. You need Git,
Bash, Python 3.10+, and access to both agents. Use a disposable clone containing
only this synthetic example; no personal imports or external integrations are
needed. See [getting started](getting-started.md) if a prerequisite is missing.

## 1. Set up one shared workspace

```bash
git clone https://github.com/conorbronsdon/agent-context-os.git handoff-demo
cd handoff-demo
bash scripts/setup.sh --agents claude,codex
```

Review the agent-selection diff before approving it. Decline optional commits,
remote changes, and hooks for this exercise. Launch `claude` from this directory,
invoke `/setup`, and answer the interview with this fictional project:

> Lantern is a small export tool. Its next task is CSV export for spreadsheet
> analysis. We considered PDF export and rejected it because users need to sort
> the data. The launch date is unconfirmed. Keep the example within this clone.

Review the proposed context files and approve that exact proposal only if it
matches these facts. The agent should report the resulting receipt.

## 2. Save one decision with Claude

Invoke `/end` and provide this handoff:

> Record the decision to implement CSV export, including why PDF was rejected.
> Next session should outline CSV columns. The launch date remains unconfirmed.

Inspect the proposed decision row and session note. Approve the exact proposal
after review. Save the receipt path the agent reports. Do not commit or push as
part of this exercise; the second agent reads the same local files.

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
